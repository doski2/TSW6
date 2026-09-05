# Freight NA — SD40-2 y multi-mando

Trenes diesel norteamericanos con **tracción + 3 frenos** separados (layout **`freight_na`** /
split).

**Producto v2:** [v2/PLAN_V2.md](../v2/PLAN_V2.md) (G-A servicio + G-B layout, §2 F-D, §4.8). Este
doc es la
referencia técnica del layout NA; no usar el plan archivado v1 como guía de producto.

---

## En v2: servicio ≠ layout

| Eje | Freight NA (SD40-2) | Class 323 (contraste) |
| --- | --- | --- |
| **Servicio (G-A)** | Vía sin horario: límites, señales, pendiente, objetivo de parada si hay | Pasajeros: ETA, andén, puertas |
| **Layout (G-B)** | **Split** — `Throttle` + `AutomaticBrake` + `DynamicBrake` | **Combined** — `PowerBrakeHandle` |
| **Holgura ETA** | **OFF** (casi nunca hora de llegada HUD) | ON si hay horario + TimeOfDay |
| **`tsw_hud.db`** | No por defecto (evita match basura) | Sí en servicios comerciales UK |
| **FSM puertas** | No | Sí (G-A) |

Mal: `if freight: … else: muescas 323` en un solo sitio. Bien: **objetivos** por servicio;
**palancas** por paquete JSON del tren (`data/vehicles/<id>.json`).

---

## Layout `freight_na`

| Eje | En juego | Telemetría (HUD / GetData) |
| --- | --- | --- |
| Tracción | Muescas 0–8 | `HUD_GetPowerHandle` → `throttle_notch` |
| Freno automático | % 0–1 | `HUD_GetTrainBrakeHandle` → `train_brake` |
| Freno independiente | % −1–1 | `HUD_GetLocomotiveBrakeHandle` → `loco_brake` |
| Freno dinámico | Muescas → 0–1 | `HUD_GetElectricBrakeHandle` → `dyn_brake` |

Escritura IPC/API: `Throttle`, `AutomaticBrake`, `IndependentBrake`, `DynamicBrake` (no
`PowerBrakeHandle`).

Plantilla esquema: `logs/control_schemas/freight_na_railbridge_v3.json` (nombre histórico).

### `combined` (UK EMU — solo referencia)

Un handle 0–8 (323: `PowerBrakeHandle`). No es freight; ver [PLAN_V2.md](../v2/PLAN_V2.md) §1 y
§4.8.

---

## Física (misma que pasajeros)

- **Un** `physics.py`: `s = v²/(2a)`. Freight = más metros porque **`a` es menor** y hay **qué eje**

  usar (F-D), no otro motor de distancia.

- **Learner por eje:** `FreightLearner` + `logs/profiles/<vehículo>.json` (matrices tracción /

  auto / dyn / ind).

- **Masa (F-B, [PLAN_V2](../v2/PLAN_V2.md) §2):** HTTP peso **total** formación, arranque + cada 5

  min
  (igual que pasajeros). `massFactor` = `mass_now / mass_ref`; no sumar por vagón en el tick.

- **Longitud formación:** no entra al plan (parada en objetivo / andén / cartel).
- **Patinaje ([PLAN_V2](../v2/PLAN_V2.md) §2):** fase 1 elegida — slip en APPLY → −1 muesca en el

  eje
  activo, plan intacto; sin +metros inventados. Fase 2 learner mojado aplazada.

---

## Selector de frenos (F-D — investigar in-game)

**Elegido en producto v2** ([PLAN_V2](../v2/PLAN_V2.md) §2, opción F-D). Implementación: fase 4 de
este
doc → [PLAN_V2](../v2/PLAN_V2.md) fase 6.

| Situación | Hipótesis v2 | Validar en TSW |
| --- | --- | --- |
| **Bajada** (pendiente &gt; ~0,5 %) | Freno **dinámico** como retención principal | SD40 con tren enganchado |
| **Velocidad sube pese a dyn** | **Blended:** dyn + automático ligero | ¿TSW modela recarga del tubo? |
| **Límite / parada / rojo** | **Automático** (reducir dyn al acercarse) | Parada final &lt; ~10 mph |
| **Freno independiente** | **Fuera del autopilot** — maniobras loco sola | No cablear en agente v2 |

El 323 combined no aplica. Distancia sigue siendo `v²/2a` con `a` del learner del eje elegido.

### Base operativa real (referencia, no reglas TSW)

Síntesis de manuales y reglas de manejo NA (BNSF, CP, circulares de seguridad). **Cada
ferrocarril varía**; esto es guía para diseñar `brake_selector.py`, no copiar literalmente al sim.

#### Qué hace cada freno

| Freno | Fuerza | Uso típico | Límites |
| --- | --- | --- | --- |
| **Dinámico (dyn)** | Retención en motores de tracción, **solo en la(s) loco(s)** | Controlar velocidad en **bajada** sin desgastar frenos de vagones; respuesta rápida | No para parar solo; fuerza concentrada en cabeza → riesgo de **fuerzas de compresión** (buff) si subes muescas muy rápido |
| **Automático (train)** | Freno neumático en **todo el tren** | Parada, límite estricto, emergencia; **complemento** si dyn no basta en pendiente | Propagación lenta en trenes largos; en US suele ser **liberación completa** (no soltar “un poco” como en UK); recargar el tubo tarda |
| **Independiente (loco)** | Solo frenos de la locomotora | Arranque, parada final a baja velocidad, estacionamiento | **No** para controlar velocidad en bajada; en blended real hay que **bail off** (soltar ind) para no patinar ruedas de loco |

#### Orden de preferencia al frenar (bajada / reducir velocidad)

Según práctica habitual y circular *Train Handling When Operating with Dynamic Brakes* (UP, 2020):

1. **Manipular tracción** (menos potencia antes de frenar).
2. **Freno dinámico** (desgaste cero en vagones, ajuste fino).
3. **Dyn + automático ligero** (“blended braking”) si la pendiente o la masa superan el dyn.

En pendiente larga con slack estirado, algunos manuales (p. ej. CP) piden **automático primero**
y subir dyn en los tramos más empinados; al pasar de aire a dyn: **aplicar dyn antes de soltar el
aire** y bajar dyn ~2 min tras la liberación para evitar run-in violento. v2 puede simplificar si
TSW no modela slack.

#### SD40-2 (EMD)

- Palanca dyn: **OFF → SETUP → 1…8 (FULL)**; throttle en **IDLE** y reversora en marcha para salir

  de OFF.

- **Pausa ~10 s** en IDLE al pasar de tracción a dyn (evita pico de retención / flashover en motor).
- Subir/bajar muescas dyn **despacio**; pausa en mínima retención para que el tren ajuste slack.
- Medidor de carga / esfuerzo: más amperaje de retención = más fuerza (útil para calibrar learner

  dyn).

#### Comportamiento vs velocidad (aprox.)

| Rango | Dyn | Automático |
| --- | --- | --- |
| **Crucero en bajada** (25–45 mph típico freight) | Principal | Solo si dyn no mantiene velocidad |
| **Aproximación a límite / señal** | Ir bajando dyn | Automático para perfil de parada (`v²/2a` con `a` del learner **auto**) |
| **Parada final** (&lt; ~10 mph) | Poca o ninguna (pierde eficacia muy abajo) | Automático hasta detenerse |
| **Emergencia** | No confiar solo en dyn | Automático servicio o emergencia |

Fuentes divergen en el piso exacto (&lt;9 mph vs &lt;10 mph); **medir en TSW** con SD40.

#### Implicaciones para el autopilot (borrador `brake_selector`)

```text
```

**Fuera de v1/v2 inicial:** slack run-in, bail off del ind, recarga del tubo, DP remoto, hand brakes
tras emergencia en pendiente.

#### Referencias web

- [SD40-2 Operator Manual §2](https://www.rr-fallenflags.org/manual/sd40-2s2.html) — palanca dyn,

  pausa 10 s.

- [Train Handling When Operating with Dynamic Brakes (UP,

  PDF)](https://lawblet13.org/wp-content/uploads/2022/08/su-2020-02T.pdf) — orden preferencia, buff
  forces.

- [BNSF Air Brake and Train Handling Rules (NTSB docket

  PDF)](https://data.ntsb.gov/Docket/Document/docBLOB?FileExtension=pdf&FileName=BNSF+Airbrake+and+Train+Handling+Rules-Rel.pdf&ID=7480227)
  — blended, grades, no ind en dyn.

- [CP Locomotive Engineer Training (NTSB docket

  PDF)](https://data.ntsb.gov/Docket/Document/docBLOB?FileExtension=pdf&FileName=CP+Loco+Eng+Training-Rel.pdf&ID=13320063)
  — combinación dyn+auto en bajada.

- [NAP — Long Freight Trains, cap. 5](https://www.nationalacademies.org/read/27807/chapter/5) —

  límites dyn, emergencia con aire.

---

## Fases de implementación (código)

| Fase | Estado | Entregable |
| --- | --- | --- |
| 0 | ✅ | Esquemas en `logs/control_schemas/` |
| 1 | ✅ | `control_layout.py`, `TrainState` multi-mando |
| 2 | ✅ | `FreightLearner`, JSON perfil v2 |
| 3 | ✅ | Monitor 4 matrices en `learn_monitor.py` |
| 4 | ⬜ | `brake_selector.py` — reglas F-D (auto / dyn) |
| 5 | ⬜ | `handle_controller` rama freight + IPC |
| 6 | ⬜ | Tracción predictiva 8 muescas (fuera de v2 inicial; tras P1 freight estable) |

**Siguiente:** fase 4 + sesión SD40 documentando umbral bajada y auto vs dyn. No mezclar con
lógica combined del 323.

---

## SD40-2 validado (2026-06-13)

| Eje | Campo | Rango |
| --- | --- | --- |
| Tracción | `throttle_notch` | 0–8 |
| Freno auto | `train_brake_handle.handle_position` | 0.0–1.0 |
| Freno ind | `locomotive_brake_handle.handle_position` | −1.0–1.0 |
| Freno dyn | `electric_brake_handle.handle_position` | 0.0–1.0 |

Detalle sesión: `logs/control_diag_BNSF_SD40-2_C_20260613_180536.txt`

---

## Calibración

`aprender.bat` → opción **2** (mercancías, 2 mph mín.).

Orden sugerido cuando las matrices freight estén completas:

1. Tracción — todas las muescas, bandas 0–30 / 30–60 / 60+ mph
2. Train brake — llano, 20–50 mph
3. Dyn brake — bajadas &gt;0,5 %, 25–45 mph (alinea con hipótesis F-D)
4. Ind brake — paradas, 5–20 mph (maniobras; autopilot no lo usa en línea)

Regla: en cada ventana de 2 s solo debe moverse **un eje**; si no, la muestra se descarta. **No**
actualizar learner durante patinaje ([PLAN_V2](../v2/PLAN_V2.md) §2).

---

## Archivos clave

| Archivo | Rol |
| --- | --- |
| `tsw6/learning/freight_learner.py` | Learner multi-eje |
| `tsw6/learning/learn_monitor.py` | UI matrices freight |
| `tsw6/learning/control_layout.py` | Detecta `combined` vs `freight_na` |
| `tsw6/autopilot/train_state.py` | Estado con 4 mandos |
| `tsw6/braking/v2/physics.py` | `v²/2a` compartido UK + NA |
| `tsw6/autopilot/handle_controller.py` | Hoy solo `combined`; fase 5 freight |

---

## Referencias

- [PLAN_V2.md](../v2/PLAN_V2.md) — producto v2 (G-A/G-B, §2 física, fase 6 freight)
- [BRAKE_V2.md](BRAKE_V2.md) — P1 compartido
- [CURRENTFORMATION_API.md](../reference/CURRENTFORMATION_API.md) — masa / patinaje HTTP
- Plan histórico v1 (solo archivo):

  [archive/docs/FREIGHT_NA_PLAN.md](../archive/docs/FREIGHT_NA_PLAN.md)
