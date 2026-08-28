# Física del frenado y aprendizaje online

Relacionado: [BRAKE_V2.md](BRAKE_V2.md) · [DASTSC_PARITY.md](DASTSC_PARITY.md) ·
[GUIA.md § Aprendizaje](GUIA.md#iniciar_autopilotbat)

---

## Resumen

| Pieza | Rol |
| --- | --- |
| `governor_constants.MAX_DECEL_MS2` | Decel de servicio máxima (base única, Class 323) |
| `braking/v2/physics.py` | Cinemática `v²/2a`, gradiente, márgenes |
| `plan.py` + `limit_brake.py` | Perfil B1/B2/B3 (fracciones 0.33 / 0.55 / 0.80) |
| `TrainPhysics` + `OnlineLearner` | Calibración por muesca y banda de velocidad |
| `aprender.bat` | Monitor **guiado** (mismo learner, conducción manual) |
| Autopilot GUI / `--learn` | Aprendizaje **en marcha** mientras conduces |

**El autopilot ya aprende** — no hace falta `aprender.bat` para que P1 use un perfil. La diferencia
es *cómo* y *qué* muescas se calibran.

---

## ¿Por qué existe `aprender.bat` si el autopilot ya tiene learner?

No son dos sistemas distintos. Ambos usan `OnlineLearner` / `FreightLearner` y guardan en
`logs/profiles/<vehículo>.json`.

| Modo | Herramienta | Cuándo | Qué aprende |
| --- | --- | --- | --- |
| **Auto-aprender (defecto)** | Autopilot GUI / CLI | Cada sesión salvo `--no-learn` | Todas las muescas 0–8 mientras conduces |
| **Solo freno** | Desmarcar Auto-aprender en GUI | Si quieres perfil estático | Decel B1–B3 + `MAX_DECEL` al frenar |
| **Guiado** | `aprender.bat` → `learn_monitor.py` | Primera calibración o tren nuevo | Matriz completa, conducción manual sistemática |

Código en `autopilot_core.tick()`:

```python
```

Con **Auto-aprender ON** (defecto desde 2026-08-25) se alimentan todas las muescas. Si lo
desactivas,
solo refina al frenar (comportamiento anterior).

`aprender.bat` sigue siendo útil para:

1. Matriz visual (muesca × banda de velocidad) y objetivo de muestras por celda.
2. Conducción **manual** sistemática (llano / subida / bajada).
3. Tren nuevo: descubrir muescas y mandos sin que el autopilot mueva el handle.

**Decisión de producto:** no fusionar el monitor en la GUI; el autopilot **afina solo** con lo ya
aprendido (y con trenes nuevos al cambiar `vehicle=` en el probe). `aprender.bat` queda para
calibración inicial opcional.

---

## Perfiles genéricos vs calibración por modelo

### Hoy

| Fuente | Qué aporta |
| --- | --- |
| `governor_constants` | `MAX_DECEL_MS2 = 1.071`, `SAFETY_MARGIN = 1.40`, fracciones B1–B3 |
| `UK_SERVICE_PHASES` | 33 % / 55 % / 80 % de `base_decel` si no hay perfil |
| `_DEFAULT_THROTTLE_CEILING` | Techos mph por muesca de tracción (Class 323) |
| `logs/profiles/<BP_TSW2_….json>` | Decel **medida** por muesca, velocidad y gradiente |

Al arrancar, `TrainPhysics.set_vehicle_profile(vehicle)` carga el JSON del tren detectado en
`GetData.txt` (`vehicle=…`). Si no existe, usa constantes por defecto.

### Propuesta: perfiles semilla (seed)

Para no empezar de cero en cada locomotora:

1. **`data/profiles/seed/`** — JSON genéricos por familia:
   - `uk_emu_combined.json` (323, 350, …)
   - `uk_dmu.json`
   - `freight_na.json`
2. Al detectar vehículo nuevo: copiar semilla más cercana → `logs/profiles/<clase>.json`.
3. Autopilot + Auto-aprender **afinan** sobre esa base en las primeras sesiones.

Fuentes para semillas (investigación manual, no en repo aún):

- Fichas reales Class 323 (decel servicio ~0.8–1.0 m/s² según carga).
- Valores Dastsc `agent_config` / `brakeStats` si existen para el mismo pack.
- Primera pasada con `aprender.bat` en ruta llana y guardar como plantilla.

**Riesgo:** una semilla mala puede frenar demasiado pronto o tarde hasta que el learner corrija.
Por eso el MVP sigue siendo: calibrar 323 una vez y validar E1.

---

## Constantes de deceleración — qué hace cada una

### Antes de unificar (confuso)

| Constante | Valor | Dónde | Uso real |
| --- | --- | --- | --- |
| `MAX_DECEL_MS2` | **1.071** | `governor_constants.py` | `TrainPhysics.eff_max_decel` → **P1 `base_decel`** |
| `DEFAULT_MAX_BRAKE_DECEL` | **0.80** | `v2/physics.py` (legacy Dastsc) | Fallback si `base_decel` no se pasa |
| Fracciones B3 | 0.80 × base | `plan.py` | B3 ≈ 0.86 m/s² con base 1.07 |

En la práctica P1 **ya usaba 1.071** vía `eff_max_decel`. El 0.80 solo afectaba tests o llamadas
directas a funciones v2 sin pasar `base_decel` — dos “verdades” distintas.

### Después de unificar (2026-08-25)

```python
```

Una sola fuente: `governor_constants.MAX_DECEL_MS2`. El learner puede **subir o bajar** ese valor
en el JSON (`MAX_DECEL_MS2` clamp 0.50–1.50); P1 lee el valor ya aprendido cada tick.

| Constante | Significado |
| --- | --- |
| `MAX_DECEL_MS2` | Techo de decel de servicio (B3 ≈ 80 % de esto) |
| `TARGET_DECEL_MS2` | Media de muescas 1–3 en learner (referencia, no planificador directo) |
| `COAST_DECEL_MS2` | Inercia mínima en distancia de frenado |
| `SAFETY_MARGIN` | ×1.40 en distancias con `apply_margin=True` |
| Fracciones 0.33/0.55/0.80 | B1/B2/B3 cuando `predict_decel` no tiene muestras |

### Ventana APPLY — de metros fijos a física (2026-08-26)

Fórmula única en `apply_zone_margin_m`:

```text
```

`apply_at` = distancia de frenado planificada (cuándo debería empezar el perfil). Se deriva de
`distance_to_target − dist_start` cuando ambos existen (`_coherent_apply_at_remaining_m`).

| Constante / función | Significado |
| --- | --- |
| `APPLY_NOW_MARGIN_MIN_M` (25) | Piso — tren lento sigue teniendo ventana |
| `APPLY_NOW_MARGIN_M` (150) | Techo — no ampliar más allá de esto |
| `speed × 2.5` | ~2.5 s de reacción a velocidad actual |
| `apply_at × 0.12` | 12 % de la distancia de frenado del plan |
| `is_in_brake_action_window` | ±zona simétrica en `dist_start` |
| `should_emit_brake_command` | ±zona **o** tarde (`dist_start < 0` y `distance ≤ apply_at`) |

**Sustituye** en código: zona APPLY 60 m, histeresis limit 80/30 m, contención bajada 150 m,
umbral B3 tarde −30 m. Detalle por módulo: [BRAKE_V2.md §
Ventana](BRAKE_V2.md#ventana-de-aplicación-2026-08-26).

| Velocidad | `apply_at` ejemplo | Zona ≈ |
| --- | --- | --- |
| 60 mph (26.8 m/s) | 400 m | **67 m** |
| 30 mph | 200 m | **50 m** |
| 10 mph | 80 m | **25 m** (mínimo) |

### Fuentes de telemetría para física

| Dato | Hoy | HTTPAPI (debate) |
| --- | --- | --- |
| `accel_ms2`, muescas | Probe `HUD_Get*` | [CURRENTFORMATION_API.md](CURRENTFORMATION_API.md) |
| `gradient_pct` | Probe / DriverAid | `DriverAid.Data.gradient` |
| Decel por muesca | Learner JSON | — |
| Masa consist | — | `ClampPowerInput.Mass`, bogies |
| Presión freno / fill time | Constante 2.5 s | `BrakeCylinder_*_Pressure` |
| Esfuerzo N | — | `HUD_GetTractiveEffort` |

Índice completo: [TSW_HTTPAPI_INDEX.md](TSW_HTTPAPI_INDEX.md)

---

## Flujo físico en un tick P1

```text
```

**Con perfil aprendido:** `predict_decel` sustituye fracciones fijas → paridad Dastsc `brakeStats`.

**Sin perfil:** fracciones × `MAX_DECEL_MS2` (1.071) — conservador para UK EMU.

---

## Comparación Dastsc

| Aspecto | Dastsc | TSW6 |
| --- | --- | --- |
| Cinemática | `physics.ts` | `v2/physics.py` |
| Decel por muesca | `brakeStats` | `OnlineLearner.predict_brake_decel_ms2` |
| Base sin stats | `baseDecel` | `MAX_DECEL_MS2` + fracciones UK |
| Masa | `massFactor(massT)` | 🟡 API `CurrentFormation` — ver [CURRENTFORMATION_API.md](CURRENTFORMATION_API.md) |
| Esfuerzo freno real | — | 🟡 `HUD_GetTractiveEffort` (debate) |
| Aprendizaje en agente | integrado | autopilot Auto-aprender (defecto) + `aprender.bat` opcional |

---

## Cómo calibrar (recomendado)

### Ruta rápida (autopilot)

1. Instalar probe; arrancar autopilot (**Auto-aprender ya activo** por defecto).
2. Conducir la ruta (manual o con P1 frenando); el perfil se guarda en `logs/profiles/`.
3. Revisar pestaña **Aprendizaje**: muestras por muesca, `MAX_DECEL` estable.
4. Validar E1: `uni=Y`, RELEASE @55, un salto IPC por fase.

### CLI

```bat
```

### Ruta completa (opcional — tren nuevo)

1. `aprender.bat` → matriz guiada (pasajeros o freight), o
2. Directamente autopilot con Auto-aprender (defecto): al cambiar `vehicle=` en el probe se crea

   `logs/profiles/<clase>.json` y P1 afina con cada sesión.

---

## Pendiente

| ID | Tema |
| --- | --- |
| L1 | Perfiles semilla `data/profiles/seed/` por familia de tren |
| L3 | Masa consist vía [CURRENTFORMATION_API](CURRENTFORMATION_API.md) → `massFactor` Dastsc |
| L4 | `HUD_GetTractiveEffort` / presión cilindro para fill time real |
| L5 | Horario: reaction scale / coast allowance en paradas |

---

## Archivos clave

| Archivo | Rol |
| --- | --- |
| `tsw6/governor/governor_constants.py` | `MAX_DECEL_MS2`, márgenes P1 |
| `tsw6/braking/v2/physics.py` | Cinemática + ventana de aplicación |
| [TSW_HTTPAPI_INDEX.md](TSW_HTTPAPI_INDEX.md) | Catálogos HTTPAPI (física pendiente) |
| `tsw6/governor/governor_physics.py` | Puente learner ↔ P1 |
| `tsw6/learning/online_learner.py` | EMA, bandas, JSON |
| `tsw6/learning/learn_monitor.py` | Monitor `aprender.bat` |
| `tsw6/autopilot/autopilot_core.py` | `feed_learner` cada tick |
| `logs/profiles/*.json` | Perfiles por vehículo |
