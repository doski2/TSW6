# CurrentFormation — catálogo HTTPAPI / física del tren

Referencia del árbol `Root/CurrentFormation` en la HTTPAPI de TSW6 (`-HTTPAPI`, puerto `31270`).

**Dump de origen (sesión real):**
`Desktop\investigacion tsw 6\apis\tsw-api-export-CurrentFormation-20260818T172120Z.json`

- Fecha captura: 2026-08-18 UTC
- Tren: **Class 323** (formación 3 vehículos, `DrivableIndex=0`)
- Ruta: Cross-City · Lichfield City
- Nodos en dump: **1227** (árbol recortado; crawler reporta ~25k endpoints bajo formación completa)

**Importante:** este árbol es la **simulación del vehículo** — masa, aire comprimido, esfuerzos,
mandos HUD. Complementa [DriverAid](DRIVERAID_API.md) (vía y límites) y
[DriverInput](DRIVERINPUT_API.md) (escritura de palancas).

**Estado TSW6:** la mayoría de campos están **disponibles en HTTP** pero **no** en el probe Lua
actual (`main.lua` solo usa `HUD_Get*` y un eje para odómetro).

---

## Cómo leer este documento

| Columna | Significado |
| --- | --- |
| **Estado** | Integración en TSW6 |
| **HTTP** | `GET http://127.0.0.1:31270/get/CurrentFormation.<ruta>` |
| **Lua** | Equivalente en cabina vía actor drivable (misma ruta sin prefijo `Root/`) |

| Estado | Significado |
| --- | --- |
| ✅ En uso | Probe o Python lo consumen |
| 🟡 Disponible | En dump; candidato física |
| ⚠️ Inestable | A menudo `INVALID` o por vehículo/eje |
| ❌ No autopiloto | Diagnóstico / editor |

**Índice de vehículo:** `/0` = unidad mando (Class 323 cabina). Otros índices = remolques del
consist.

**Unidades observadas (dump Class 323):**

| Magnitud | Unidad API | Notas |
| --- | --- | --- |
| `HUD_GetSpeed` | m/s | × 2.236936 → mph |
| `HUD_GetAcceleration` | m/s² | Coherente con probe `accel_ms2` |
| `HUD_GetTractiveEffort` | N (newtons) | `TractiveEffort`, `BrakeEffort` |
| `BrakeGauge_*` | Pa | Manómetros cabina |
| `Axle_*_SpeedAtRail_MPH` | mph | Velocidad en rail por eje |
| `*.Mass` | kg (UE) | Bogie ~5000, eje ~1000 en dump |
| `CurrentTrackAdhesion` | 0–1 | ~0.99 en dump seco |

---

## Nivel formación

| Campo | Tipo | Estado | Qué es |
| --- | --- | --- | --- |
| `FormationLength` | int | 🟡 | Vehículos en el consist (3 en dump) |
| `DrivableIndex` | int | 🟡 | Índice del vehículo que conduces (0) |

---

## `Function.HUD_Get*` — telemetría de cabina (vehículo `/0`)

**HTTP:** `GET /get/CurrentFormation/0.Function.HUD_GetSpeed` (y análogos)

Estos son los mismos que llama el probe Lua. Valores del dump con tren **parado**, freno B1, power
−1 (neutro con ligera tracción negativa).

| Función | Valor ejemplo dump | Estado TSW6 | Uso física / frenado |
| --- | --- | --- | --- |
| `HUD_GetSpeed` | ~0 m/s | ✅ probe | Velocidad |
| `HUD_GetAcceleration` | ~9.3×10⁻⁵ m/s² | ✅ probe | Learner, `physics.py` |
| `HUD_GetPowerHandle` | `Power: -1`, `IsNegative: true` | ✅ probe | Muesca combinada UK |
| `HUD_GetTrainBrakeHandle` | `HandlePosition: 0.33` | ✅ probe | B1 (~⅓) |
| `HUD_GetLocomotiveBrakeHandle` | inactivo Class 323 | ✅ probe | Freight |
| `HUD_GetElectricBrakeHandle` | `0.33` | ✅ probe | Regenerativo / dinámico |
| `HUD_GetDirection` | `Direction: 1` | 🟡 | Forward / reverse |
| `HUD_GetIsSlipping` | `false` | 🟡 | Patinaje (booleano) |
| `HUD_GetIsTractionLocked` | `false` | 🟡 | Bloqueo tracción |
| `HUD_GetTractiveEffort` | ver tabla abajo | 🟡 | `BrakeEffort` parado; `TractiveEffort` suele 0 |
| `HUD_GetBrakeGauge_1` | `Red/WhiteNeedle (Pa)` | 🟡 | Presión indicada cabina |
| `HUD_GetBrakeGauge_2` | idem | 🟡 | Segundo manómetro |
| `HUD_GetMaxPermittedSpeed` | inactivo | 🟡 | ATS / techo |
| `HUD_GetSpeedControlTarget` | inactivo | ❌ | Cruise (no 323) |
| `HUD_GetAmmeter` | 0 | ❌ | Tracción eléctrica |
| `HUD_GetEngineRPM` | 0 | ❌ | Diesel |

### Debate: `HUD_GetTractiveEffort`

**Dos sesiones live Class 323 (2026-08-26):**

| Condición | B1 (0.33) | B2 (0.67) | B3 (1.0) | Notas |
| --- | --- | --- | --- | --- |
| **Parado** (`acc≈0`) | BE **5921 N**, P **2.61 BAR** | BE **9347 N**, P **3.54 BAR** | BE **4.8×10²⁰** ❌, P **4.28 BAR** | B3 effort = basura; presión OK |
| **En marcha** (frenando) | BE **0**, P **~5.3 BAR** | — | — | Presión sí; effort no |

- **`BrakeEffort (N)`:** útil **parado** en B1–B2 (escala ~6k → ~9k N). En B3 el sim devuelve

  overflow — en código: descartar si `BrakeEffort > 50_000` o `!= BrakeEffort`.

- **`TractiveEffort (N)`:** sigue en 0 en las pruebas.
- **Presión cilindro** fiable en ambos regímenes; preferir para fill-time y learner.

**Prueba mínima en marcha:** repetir el comando HTTP mientras frenas a 30–40 mph y comparar BE vs
P21.

**HTTP:** `GET /get/CurrentFormation/0/Simulation/BrakeCylinder_2_1.Pressure_BAR`

**Probe Lua:** `brake_cyl_bar` (mismo nodo vía `actor.Simulation.BrakeCylinder_2_1`).

---

## Simulación de freno de aire

Nodos `Property.Simulation_<nombre>_<parámetro>` — en dump muchos devuelven **referencia interna**
(`nodeReference`) en lugar del valor numérico directo; hay que resolver o leer vía función HUD.

| Nodo Simulation | Parámetro | Estado | Interés |
| --- | --- | --- | --- |
| `BrakeCylinder_1_1` | `Pressure` | 🟡 | Presión cilindro — **tiempo de llenado** |
| `MR (AirPipe)` | `Pressure_BAR` / `Pressure` | ⚠️ INVALID en dump parado | Depósito principal |
| `Brake Reservoir Tank` | `Pressure_BAR` | ⚠️ INVALID | Depósito auxiliar |
| `BrakeInput` | `InputValue` | 🟡 | Entrada mando freno (sim) |
| `EBrakeInput` | `InputValue` | 🟡 | Emergencia |
| `ParkingBrakeApplication` | `ValvePosition` | 🟡 | Freno estacionamiento |
| `AirCompressor` / `AuxCompressor` | varios | ❌ | Compresores |

**Propiedades de estado (vehículo `/0`):**

| Campo | Estado | Qué es |
| --- | --- | --- |
| `BrakeHoldNotch` | 🟡 | Muesca de retención (3 en dump) |
| `MainResPipeEmergencyState` | 🟡 | Emergencia aire |
| `IsWheelSlipping` | 🟡 | Patinaje global |

### Debate: sustituir `DEFAULT_BRAKE_FILL_S = 2.5`

Hoy `physics.reaction_margin_m` usa **2.5 s fijos** de llenado. Si `BrakeCylinder_Pressure`
sube con curva conocida, el planificador podría usar **distancia de reacción dinámica** por
muesca (B1 más lento que B3).

---

## Masa, adherencia y patinaje

Extraído del subárbol `Simulation` por vehículo (valores **varían** por índice de carro).

| Endpoint | Ejemplo dump | Estado | Uso |
| --- | --- | --- | --- |
| `ClampPowerInput.Mass` | **45480** (unidad mando) | 🟡 | Masa total vehículo lider |
| `LoadSensingBrakeModifier.Mass` | 0 / 3640 | 🟡 | Modificador carga → freno |
| `Bogie_1.Mass` / `Bogie_2.Mass` | 5000 | 🟡 | Por bogie |
| `Axle_*_1.Mass` | 1000 | 🟡 | Por eje |
| `Axle_*_1.CurrentTrackAdhesion` | ~0.99 | 🟡 | Adherencia pista |
| `Axle_*_1.IsSlipping` | bool | 🟡 | Patinaje eje |
| `TM_*_1.Slip` / `SlipSpeed` | ~0.99 / 0.11 | 🟡 | Motor tracción |
| `RailVehiclePhysicsComponent0.Function.GetMassOfCargo` | 0 | 🟡 | Carga (freight) |

### Debate: masa en `braking_distance_m`

```text
```

Hoy usamos `MAX_DECEL_MS2` **aprendido** (empírico). Con masa del consist:

- Pasajeros llenos vs vacío → misma muesca, distancia distinta.
- **Propuesta:** `effective_mass_kg` en probe = suma `ClampPowerInput.Mass` de la formación;

  escalar `base_decel` o `predict_decel`.

---

## Otros `Property` útiles (vehículo `/0`)

| Campo | Estado | Notas |
| --- | --- | --- |
| `HIllStartMaxSpeed` | 🟡 | ~1.34 m/s (~3 mph) — arranque en rampa |
| `IsMoving` | 🟡 | Booleano movimiento |
| `ManualSanderIsActive` | 🟡 | Arena |
| `Simulation_Axle_2_1_SpeedAtRail_MPH` | 🟡 | Velocidad rail (ya usamos `Axle_1_1` en Lua para odómetro) |
| `Simulation_HUD_Accelerometer_RateOfChangeSmoothed` | 🟡 | Acelerómetro suavizado (alternativa a `HUD_GetAcceleration`) |

---

## Qué NO está aquí

| Dato | Dónde |
| --- | --- |
| Límite de velocidad adelante | [DriverAid.Data](DRIVERAID_API.md) |
| Distancia a estación / cartel | DriverAid + `tsw_hud.db` |
| Escribir palanca combinada | [DriverInput.PowerBrakeHandle](DRIVERINPUT_API.md) o IPC |
| Horario comercial | [TimeOfDay](TIMEOFDAY_API.md) + HUD DB |

---

## Mapa implementación propuesta

| Campo API | Prioridad | Archivo TSW6 destino |
| --- | --- | --- |
| `HUD_GetTractiveEffort` | Alta | `tsw_telemetry_source.py`, learner |
| `BrakeCylinder_*_Pressure` | Alta | `physics.py` (fill time) |
| Suma `*.Mass` formación | Media | `physics.py`, `TrainPhysics` |
| `CurrentTrackAdhesion` | Media | `limit_brake.py` bajadas |
| `HUD_GetBrakeGauge_*` | Baja | GUI diagnóstico |
| `trackHeights` | Baja | [DriverAid](DRIVERAID_API.md) (no CurrentFormation) |

---

## Referencias

| Archivo | Relación |
| --- | --- |
| [TSW_HTTPAPI_INDEX.md](TSW_HTTPAPI_INDEX.md) | Índice de todos los árboles |
| [DRIVERAID_API.md](DRIVERAID_API.md) | Vía y planning |
| [FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md) | Constantes + ventana APPLY física |
| `mods/TelemetryProbeMod/Scripts/main.lua` | HUD_Get* ya cableados |
| `tsw6/telemetry/tsw_telemetry_source.py` | Poll HTTP opcional |

---

## Bitácora

| Fecha | Nota |
| --- | --- |
| 2026-08-18 | Dump completo Class 323, 3 vehículos |
| 2026-08-26 | Parado: BE B1/B2 OK, B3 overflow; P21 escala B1&lt;B2&lt;B3; en marcha BE=0 |

*Pendiente:* repetir dump con tren **en movimiento** (B1/B3, rampa −1 %) para presiones y
esfuerzos no nulos; validar freight (SD40-2) para `GetMassOfCargo`.
