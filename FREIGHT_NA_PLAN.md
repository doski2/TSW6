# Plan de soporte NA Freight — BNSF SD40-2 y trenes multi-mando

## Objetivo

Extender el sistema de calibración (`aprender.bat` / `learn_monitor.py`) y el autopiloto
para trenes de mercancías norteamericanos como el **BNSF SD40-2**, que tienen:

- **Varias muescas de tracción** (típicamente 8, no 4 como el Class 323)
- **Tres tipos de freno independientes** (automático, independiente, dinámico)

El perfil actual `logs/profiles/BNSF_SD40_2_C.json` está vacío porque el código
asume un único mando combinado estilo UK (`PowerBrakeHandle` 0–8). Ese modelo
no describe cómo funciona el SD40-2 en TSW6.

---

## Estado actual del proyecto

### Lo que ya funciona (Class 323 — layout `combined`)

| Componente | Comportamiento |
|---|---|
| `learn_monitor.py` | Calibra muescas 0–8 del handle combinado |
| `online_learner.py` | EMA por muesca × banda velocidad × banda gradiente |
| `aprender.bat` | Modo pasajeros (5 mph) y mercancías (2 mph) |
| `speed_decider.py` P3 | Selector predictivo de muesca mínima (tracción) |
| `tsw_autopilot.py` | Carga perfil en solo-lectura; `--learn` opcional |
| Perfil ejemplo | `logs/profiles/RVM_BCC_WRM_Class323_DMS_A_C.json` (~500 muestras) |

### Lo que NO funciona aún (NA freight — layout `freight_na`)

| Problema | Causa |
|---|---|
| `BNSF_SD40_2_C.json` vacío | Solo se lee `throttle_notch`; frenos no cambian ese campo |
| Autopiloto no frena bien en SD40-2 | `HandleController` usa RPC `PowerBrakeHandle` + teclas A/D |
| Learner no distingue tipos de freno | Un solo eje `notch 0–8` |
| Monitor muestra matriz UK | No refleja train / ind / dyn brake |

### Referencia RailBridge — controles separados (`tsw-en.yaml`)

Fuente: `%AppData%\RailBridge\config\profiles\user\tsw-en.yaml`

| Control lógico | ID RailBridge | **Endpoint TSW** (escritura) | Teclas EN/US | Tipo | Uso típico |
|---|---|---|---|---|---|
| Tracción | `power` | `Throttle` | A / D | axis (muescas) | Potencia diesel |
| Freno automático | `train_brake` | `AutomaticBrake` | `'` / `;` | axis (% + fases) | Frena todo el tren |
| Freno independiente | `ind_brake` | `IndependentBrake` | `]` / `[` | axis (%) | Freno de locomotora |
| Freno dinámico | `dyn_brake` | `DynamicBrake` | `.` / `,` | axis (muescas) | Retención en bajada |
| Lap (fase) | `move_to_lap` | — | `/` | botón | Posición lap del freno auto |

**Importante:** `endpoint` es el nombre en la API de **escritura** de TSW (`DriverInput/*`).
La telemetría del companion SSE puede usar otros nombres (`throttle_notch`,
`brake_gauges.automatic`, `automatic_brake_status`). Los `*_brake_handle` que
buscábamos son del layout UK (`PowerBrakeHandle`), no de estos endpoints NA.

**Para Fase 5 (HandleController):** escribir vía RPC usando `Throttle`, `AutomaticBrake`,
`IndependentBrake`, `DynamicBrake` — no `PowerBrakeHandle`.

### Telemetría disponible en companion (parcialmente sin usar)

El stream `companion_dmi_delta` expone en `controls` (entre otros):

- `throttle_notch` — **confirmado SD40-2: muescas 0–8** (0 = ralentí)
- `train_brake_handle.handle_position` — **0.0–1.0** freno automático (% normalizado) ✅
- `locomotive_brake_handle.handle_position` — **-1.0–1.0** freno independiente ✅
- `electric_brake_handle.handle_position` — **0.0–1.0** freno dinámico (muescas → fracción) ✅
- `electric_brake_handle.is_active` — dyn brake enganchado (bool)
- `train_brake_notch` — objeto presente pero **provenance: unavailable** (fase/muesca discreta)

**Modelo observado en cabina (usuario, SD40-2):**

| Eje | Representación en juego | Telemetría esperada |
|---|---|---|
| Tracción | Muescas 0–8 | `throttle_notch` ✅ |
| Freno automático | **% 0–1** | `train_brake_handle.handle_position` ✅ |
| Freno independiente | **% -1–1** | `locomotive_brake_handle.handle_position` ✅ |
| Freno dinámico | **Muescas → 0–1** | `electric_brake_handle.handle_position` ✅ |

El `ammeter` correlaciona con tracción/dyn brake (negativo = retención) pero **no
es posición del mando** — no usar para calibración.

---

## Modelo de control: `combined` vs `freight_na`

### Layout `combined` (UK EMU — Class 323)

```
handle_notch 0–8 en un solo eje:
  0 = freno máx … 4 = neutro … 8 = tracción máx
```

Archivos que asumen este modelo:

- `train_state.py` — `throttle_notch`, `brake_notch` derivados de `handle_notch`
- `handle_controller.py` — RPC `PowerBrakeHandle`, teclas A/D
- `online_learner.py` — `_OBSERVED = {0..8}`
- `speed_decider.py` — `th_n` 0–4 (zona tracción del handle combinado)

### Layout `freight_na` (diesel NA — SD40-2, etc.)

```
Cuatro ejes independientes (valores Fase 0 — SD40-2):

  throttle_notch      : 0 = ralentí, 1–8 = muescas tracción ✅
  train_brake         : % aplicación + fase (liberado/lap/servicio/emergencia)
  ind_brake           : % aplicación + fase
  dyn_brake           : muescas discretas (off → setup → grados dyn)
```

**Regla de aprendizaje multi-eje:** en cada ventana de 2 s solo debe moverse
**un** eje; los demás deben permanecer estables. Si cambian dos a la vez,
la muestra se descarta (`muesca inestable`).

---

## Esquema de perfil JSON (nuevo — Fase 2)

```json
{
  "schema_version": 2,
  "layout": "freight_na",
  "vehicle": "BNSF SD40-2 C",
  "throttle": {
    "ema_bands": [{}, {}, {}],
    "n_bands": [{}, {}, {}]
  },
  "train_brake": {
    "ema_bands": [{}, {}, {}],
    "n_bands": [{}, {}, {}]
  },
  "ind_brake": {
    "ema_bands": [{}, {}, {}],
    "n_bands": [{}, {}, {}]
  },
  "dyn_brake": {
    "ema_bands": [{}, {}, {}],
    "n_bands": [{}, {}, {}]
  },
  "ema_grad_bands": [[], [], []],
  "n_grad_bands": [[], [], []]
}
```

Los perfiles `combined` existentes (Class 323) siguen en formato actual
(`ema_bands` en raíz) para no romper compatibilidad.

---

## Plan por fases

### Fase 0 — Descubrimiento de telemetría SD40-2

**Estado:** 🟡 En curso — herramienta `control_diag.py` lista; falta sesión manual en juego.

**Objetivo:** documentar los valores reales que envía el companion para el SD40-2.

**Entregables:**

- [x] Script `control_diag.py` + `diag_controles.bat` — imprime en vivo:
  ```
  Tracción (throttle_notch)     valor=3    API: throttle_notch
  Freno automático            valor=?    API: train_brake_handle
  ...
  ```
- [x] `tsw_connection.py` — lee y persiste los 4 mandos (+ snapshot crudo `raw_controls`)
- [ ] Tabla de rangos anotada en *Resultados Fase 0* (tras sesión en juego)
- [ ] Confirmar si `throttle_notch` usa escala 0–8 solo-tracción o combinada

#### Cómo ejecutar la sesión (paso a paso)

1. Arrancar **TSW6** y **RailBridge** (botón **CMP** activo).
2. Cargar ruta con **BNSF SD40-2** y subir a la cabina (tren encendido).
3. Ejecutar **`diag_controles.bat`** (o `python control_diag.py --save`).
4. Esperar a que aparezca el nombre del tren en la cabecera.
5. **Solo tracción:** subir/bajar muescas con **A / D** — anotar min y max.
6. **Solo freno automático:** teclas **`'` / `;`** — anotar min y max.
7. **Solo freno independiente:** teclas **`]` / `[`** — anotar min y max.
8. **Solo freno dinámico:** teclas **`.` / `,`** — anotar min y max.
9. **Ctrl+C** — revisar resumen en pantalla y archivo en `logs/control_diag_*.txt`.
10. Copiar min/max a la tabla *Resultados Fase 0* más abajo.

**Importante:** mover **un solo mando** cada vez. Si dos cambian a la vez, anótalo
(eso validará el filtro “muesca inestable” del learner en Fase 2).

**Criterio de aceptación:** los cuatro ejes tienen min y max conocidos antes de Fase 1.

**Archivos:** `control_diag.py`, `diag_controles.bat`, `tsw_connection.py`

---

### Fase 1 — Telemetría multi-control

**Estado:** ✅ Completa (2026-06-13)

**Objetivo:** `TswConnection` y `TrainState` exponen los cuatro mandos.

**Entregables:**

- [x] `tsw_connection.py` — `get_telemetry()` incluye frenos + `vehicle_name` + `control_layout`
- [x] `train_state.py` — campos freight + `control_layout: "combined" | "freight_na"`
- [x] `control_layout.py` — detección por esquema Fase 0 + heurísticas (`SD40`, `BNSF`, `ES44`…)
- [x] Class 323 sigue en `combined` sin cambios de comportamiento

**Criterio de aceptación:** `conn.get_telemetry()` devuelve los 4 valores en sesión SD40-2.

**Archivos:** `tsw_connection.py`, `train_state.py`, `control_layout.py`, `train_labels.py`

---

### Fase 2 — Learner multi-eje

**Estado:** ✅ Completa (2026-06-13)

**Objetivo:** calibración por eje; `BNSF_SD40_2_C.json` con datos reales (schema v2).

**Entregables:**

- [x] `freight_learner.py` — `FreightLearner` con 4 ejes
- [x] `feed(axis, level, speed, grad, accel, controls)` — un eje estable por ventana
- [x] `predict_accel` / `predict_decel` por eje
- [x] JSON `schema_version: 2`, `layout: freight_na` por eje
- [x] `create_learner()` — elige OnlineLearner vs FreightLearner
- [x] `governor_physics.py` + `learn_monitor.py` — integración básica

**Criterio de aceptación:** tras sesión de tracción, `throttle` en JSON tiene muestras;
tras sesión de train brake, `train_brake` tiene muestras.

**Archivos:** `freight_learner.py`, `online_learner.py`, `governor_physics.py`, `learn_monitor.py`, `test_freight_learner.py`

---

### Fase 3 — Monitor `aprender.bat` multi-mando

**Estado:** ✅ Completa (2026-06-13)

**Objetivo:** UI de aprendizaje con 4 matrices (tracción + 3 frenos).

**Entregables:**

- [x] `learn_monitor.py` — detectar `layout` y mostrar bloques según tren
- [x] Matriz tracción: filas = muescas power (N1–N8)
- [x] Matrices frenos: train / ind / dyn con etiquetas correctas
- [x] Hints adaptativos por eje ("mantén train brake ~2s…")
- [x] `aprender.bat` — sin cambio de menú; detección automática de layout
- [x] Diagnóstico `Estado learner` indica eje activo

**Criterio de aceptación:** monitor usable para calibrar SD40-2 sin confusión con matriz UK.

**Archivos:** `learn_monitor.py`, `train_labels.py`, `test_learn_monitor_freight.py`

---

### Fase 4 — Estrategia de frenado (`BrakeSelector`)

**Objetivo:** el decisor elige **qué freno** usar, no solo "bajar muesca".

| Situación | Freno preferido | Motivo |
|---|---|---|
| Ajuste fino / bajada larga | Dinámico | Sin desgaste, retención en pendiente |
| Reducción de límite / distancia media | Train brake (servicio) | Frena todo el consist |
| Parada precisa / andén | Ind brake | Control fino de la loco |
| Overspeed grave / emergencia | Train brake máx (+ dyn si hay) | Máxima deceleración |

**Entregables:**

- [ ] `brake_selector.py` — `select_brake(a_target, speed, grad, dist_stop, layout)`
- [ ] Integración en `speed_decider.py` P1/P2 (frenado) solo si `layout == freight_na`
- [ ] Fallback a lógica `combined` para Class 323

**Criterio de aceptación:** en simulación/tests, bajada larga elige dyn; parada corta elige ind.

**Archivos:** nuevo `brake_selector.py`, `speed_decider.py`, `test_brake_selector.py`

---

### Fase 5 — Ejecución de control freight

**Objetivo:** `HandleController` envía comandos al mando correcto.

| Acción | Layout `combined` | Layout `freight_na` |
|---|---|---|
| ACCELERATE | `PowerBrakeHandle` ↑ / A | RPC `power` ↑ / A |
| COAST | `PowerBrakeHandle` ↓ / D | RPC `power` → ralentí / D |
| BRAKE | handle combinado ↓ | `BrakeSelector` → train/ind/dyn |
| HARDBRAKE | handle → 0 | train_brake máx + dyn si aplica |

**Entregables:**

- [ ] `handle_controller.py` — rama `freight_na` con RPC `power`, `train_brake`, `ind_brake`, `dyn_brake`
- [ ] Fallback teclado según `tsw-en.yaml`
- [ ] `force_neutral` freight: ralentí en power, liberar frenos por separado

**Criterio de aceptación:** autopiloto acelera y frena SD40-2 sin tocar el mando equivocado.

**Archivos:** `handle_controller.py`, `tsw_keys.py` (teclas de freno NA)

---

### Fase 6 — P3 predictivo tracción 8 muescas

**Objetivo:** reutilizar selector predictivo ya implementado para 8 muescas diesel.

**Entregables:**

- [ ] `_select_notch_predictive` usa rango 1–8 (no 1–4) si `layout == freight_na`
- [ ] `predict_accel("throttle", notch, …)` con datos del perfil SD40-2
- [ ] Tests con perfil sintético 8 muescas

**Criterio de aceptación:** a 15 mph con a_target=0.15, elige muesca mínima según perfil (no siempre máx).

**Archivos:** `speed_decider.py`, `test_speed_decider.py`

**Nota:** gran parte del código P3 predictivo ya existe; esta fase es adaptación de rangos.

---

## Orden de implementación y esfuerzo estimado

| Fase | Descripción | Esfuerzo código | Dependencias |
|:---:|---|:---:|:---:|
| **0** | Descubrimiento telemetría | 1 sesión manual | — |
| **1** | Telemetría multi-control | ~2 h | Fase 0 |
| **2** | Learner multi-eje | ~4 h | Fase 1 |
| **3** | Monitor 4 matrices | ~3 h | Fase 2 |
| **4** | BrakeSelector | ~3 h | Fase 2 |
| **5** | HandleController freight | ~4 h | Fase 4 |
| **6** | P3 predictivo 8 muescas | ~1 h | Fase 2 |

**Total estimado:** ~17 h desarrollo + 2–3 sesiones de calibración con `aprender.bat`.

---

## Calibración recomendada (usuario)

### Mientras Fase 0–2 no estén listas

- Usar `aprender.bat` → **opción 2 (mercancías, 2 mph)**
- Calibrar **solo tracción**: mantener cada muesca de power ≥2 s a >2 mph
- Los frenos **no se grabarán** hasta Fase 2; anotar manualmente qué muesca usas

### Cuando Fase 3 esté lista (orden sugerido)

1. **Tracción** — todas las muescas, bandas 0–30 / 30–60 / 60+ mph
2. **Train brake** — lap y servicio en llano, velocidades 20–50 mph
3. **Dyn brake** — bajadas >0.5%, velocidades 25–45 mph
4. **Ind brake** — aproximación a parada, velocidades 5–20 mph

---

## Resultados Fase 0 (rellenar tras sesión diagnóstico)

**Estado: ✅ COMPLETA** — esquema guardado en `logs/control_schemas/`.

| Archivo | Contenido |
|---|---|
| `logs/control_schemas/freight_na_railbridge_v3.json` | **Plantilla reutilizable** para diesel NA (campos API, rangos, endpoints TSW) |
| `logs/control_schemas/BNSF_SD40_2_C.json` | Validación concreta del SD40-2 (sesión final) |

### Sesión final validada — BNSF SD40-2 C (`control_diag_BNSF_SD40-2_C_20260613_180536.txt`)

| Eje | Campo API | Mín | Máx | Notas |
|---|---|:---:|:---:|---|
| Tracción | `throttle_notch` | 0 | 8 | Parser corregido ✅ |
| Freno automático | `train_brake_handle.handle_position` | **0.0** | **1.0** | % normalizado |
| Fase freno auto | — | — | — | No expuesta por API |
| Freno independiente | `locomotive_brake_handle.handle_position` | **-1.0** | **1.0** | 0 = neutro |
| Freno dinámico | `electric_brake_handle.handle_position` | **0.0** | **1.0** | Muescas → fracción 0–1 |
| Dyn activo | `electric_brake_handle.is_active` | False | True | Enganche dyn brake |

### Sesiones anteriores (historial)

- **#1** `170638` — solo tracción (parser plano, frenos no visibles)
- **#2** `173115` — frenos en API anidada; resumen mostraba `True` (bug corregido)
- **#3** `180536` — **validación final** con `train_brake_pct` / `ind_brake_pct` correctos

**Estructura RailBridge v3:** cada freno es un objeto con `handle_position`, `is_active`.
No usar `is_active` como posición del mando.

**`running-train.yaml`:** no aplica al SD40-2 (un solo freno). Usar **`tsw-en.yaml`**.

---

## Fase 0 para futuros trenes NA

**Hipótesis:** cualquier diesel NA con perfil `tsw-en` y 4 mandos separados (ES44, GP38,
otro SD40, etc.) debería usar el **mismo esquema** `freight_na_railbridge_v3`.

**Comprobación rápida (~3 min)** — no hace falta repetir toda la Fase 0:

1. `diag_controles.bat` con el tren nuevo en cabina
2. Mover **un mando a la vez** y confirmar que cambian los mismos campos API
3. Si coinciden → añadir el nombre del tren a `validated_vehicles` en
   `freight_na_railbridge_v3.json` y crear `logs/control_schemas/<NombreTren>.json`
   (copiar plantilla de `BNSF_SD40_2_C.json`)
4. Si algún campo difiere → guardar el log, anotar en este plan y revisar el esquema

**Trenes UK / EMU** (Class 323, etc.) siguen en layout `combined` — no usar este esquema.

---

## Seguimiento de fases

| Fase | Estado | Fecha | Notas |
|:---:|---|---|---|
| 0 | ✅ Completa | 2026-06-13 | Esquema `freight_na_railbridge_v3.json` |
| 1 | ✅ Completa | 2026-06-13 | `control_layout.py` + `TrainState` multi-mando |
| 2 | ✅ Completa | 2026-06-13 | `FreightLearner` + JSON v2 |
| 3 | ✅ Completa | 2026-06-13 | Monitor 4 matrices freight |
| 4 | ⬜ Pendiente | | |
| 5 | ⬜ Pendiente | | |
| 6 | ⬜ Pendiente | | |

---

## Referencias en el repositorio

| Archivo | Relación |
|---|---|
| `FREIGHT_NA_PLAN.md` | Este plan (fases 0–6) |
| `control_diag.py` | **Fase 0** — diagnóstico mandos en vivo |
| `diag_controles.bat` | Lanzador Fase 0 |
| `train_labels.py` | Etiquetas de mandos UK/freight + `get_vehicle_name` |
| `logs/profiles/RVM_BCC_WRM_Class323_DMS_A_C.json` | Perfil de referencia UK |
| `logs/control_schemas/freight_na_railbridge_v3.json` | **Fase 0** — plantilla controles NA reutilizable |
| `logs/control_schemas/BNSF_SD40_2_C.json` | Validación Fase 0 del SD40-2 |
| `logs/profiles/BNSF_SD40_2_C.json` | Perfil de calibración (vacío hasta Fase 2) |
| `aprender.bat` | Lanzador monitor; opción 2 = mercancías 2 mph |
| `learn_monitor.py` | Monitor de aprendizaje guiado |
| `freight_learner.py` | **Fase 2** — learner multi-eje + JSON v2 |
| `online_learner.py` | Learner layout `combined` (Class 323) |
| `speed_decider.py` | P3 predictivo (tracción) |
| `handle_controller.py` | Ejecución `PowerBrakeHandle` (solo `combined` hoy) |
| `control_layout.py` | **Fase 1** — detección `combined` vs `freight_na` |
| `train_state.py` | **Fase 1** — `TrainState` con 4 mandos + layout |
| `tsw_connection.py` | Telemetría companion + `get_telemetry()` enriquecido |
| `%AppData%\RailBridge\config\profiles\user\tsw-en.yaml` | Mapa teclas/controles TSW EN |

---

## Próximo paso

**Fase 4:** `brake_selector.py` — el autopiloto elige qué freno usar (auto / ind / dyn).

**Calibración en juego:** `aprender.bat` → opción **2** (mercancías) con SD40-2.
