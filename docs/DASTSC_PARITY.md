# Paridad Dastsc — TSW6 ↔ Dastsc

**Objetivo:** mismo comportamiento de frenado que `C:\Users\doski\Dastsc` (nexus-agent + commandBus

+ IPC).

Trabajo en paralelo: cambios de algoritmo en Dastsc se portan aquí; cambios de probe/TSW API solo en
TSW6.

**P1 activo:** ver [BRAKE_V2.md](BRAKE_V2.md). Todo en `tsw6/braking/v2/`.

---

## Arquitectura Dastsc (referencia)

```text
```

**Sin** COAST/BRAKE genéricos en P1: el plan devuelve **B1/B2/B3** y el bus escribe el **notch
absoluto**.

---

## Estado TSW6 (2026-08-24)

### ✅ Hecho

| Pieza | TSW6 | Dastsc |
| --- | --- | --- |
| IPC GetData/SendCommand | `tsw_ue4ss_reader`, `tsw_ipc_bus` | SendCommand.txt |
| P1 v2 límite + estación + prioridad | `braking/v2/` | `planBrake.ts` + `selectUrgentBrakePlan` |
| Comando notch directo P1 | `v2/command.py` + `HandleController` IPC | `commandBus.buildBrakeCommand` |
| **RELEASE al objetivo** | `v2/command.py` | `resolveReleaseAction` |
| **Anti-rebrake (coast latch)** | `BrakeReleaseState` | `shouldInhibitLimitRebrake` |
| GUI fase plan | `B2 →N2` en barra Acción | horizon UI |
| Emergencias P1 | `v2/emergency.py` | similar |
| FSM estación / overspeed | `speed_decider.py` | P1 + watchdog |
| **Horario HUD (planning + GUI)** | `hud_timetable.py` + `tsw_hud.db` | `schedule.ts` (parcial) |
| **Paradas `car_stop_signs`** | Distancia planning (`hud_geo`) | — |
| Parada unificada cartel+andén | `v2/cluster.py` + `priority.py` | cluster |
| Gradiente en distancia freno | `v2/physics.py` (`gradient_pct`) | `gravityAcceleration` (‰) |
| Decel por muesca (aprendida) | `OnlineLearner` → `predict_decel` | `brakeStats` / `planningDecelFromStats` |

### 🔄 En curso / siguiente

| Pieza | Prioridad |
| --- | --- |
| `planBrakeForSignal` (DANGER) — telemetría | Media |
| Recalcular distancia tablón cada tick (GPS/OCR) | Media |
| Horario — reaction scale / coast allowance en coordinator | Media |
| Perfil por tren (`agent_config` JSON) | Media |
| Perfiles semilla UK EMU (`data/profiles/seed/`) | Media — ver [FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md) |
| **Masa tren (`massT`) en física P1** | Baja (freight) — ver abajo |
| Freight split-brake (throttle + train_brake) | Baja (SD40-2) |
| Modos SUGGEST / ARM / AUTO | Baja (GUI) |

### Masa del tren — gap de paridad (2026-08-24)

**Dastsc** escala la deceleración sin stats aprendidas:

```text
```

`massFactor(massT) = massT / 500` (toneladas). El snapshot lleva `train.massT` (ej. 180 t EMU, 582 t
freight).

**TSW6** no lee masa ni aplica `massFactor`. Usa `decel_for_notch()` + **gradiente** y, si hay
calibración, `OnlineLearner.predict_brake_decel()` — el peso queda **implícito** en las muestras de
`aprender.bat` o Auto-aprender.

**Base de deceleración unificada (2026-08-25):** `DEFAULT_MAX_BRAKE_DECEL` en `v2/physics.py` =
`MAX_DECEL_MS2` en `governor_constants` (1.071 m/s²). Detalle:
[FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md).

| Situación | ¿Basta sin `massT`? |
| --- | --- |
| Class 323 UK + perfil aprendido en ese consist | ✅ Sí (MVP actual) |
| Cambiar carga o otro tren sin re-aprender | ⚠️ Distancia de freno puede desviarse |
| SD40-2 freight vacío/cargado | ❌ Conviene masa (`GetMassOfCargo`) o `massFactor` portado |

**No bloquea** E1 (validar in-game 323). **Sí** entra en roadmap freight / paridad física completa.
Telemetría futura: `Simulation/RailVehiclePhysicsComponent0.GetMassOfCargo` (ver
[PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md) catálogo probe).

### TSW6 extra (no en Dastsc brake module)

+ SafetyWatchdog exceso persistente
+ Marcador freno DMI advisory
+ FSM estación UK (puertas, OCR, creep)
+ Solo-frenado (sin ACCELERATE automático)

---

## Pipeline P1 actual (v2)

```text
```

Sin plan P1: `HOLD` (watchdog teclado si exceso persistente).

---

## Cómo validar in-game

1. `install_ue4ss_probe.bat` + reiniciar GUI
2. Acercarse a límite más bajo con tracción manual
3. En **Depuración**: `v2 SPEED_LIMIT B2 distStart=…`
4. En **Acción**: `B2 →N2` (no solo `BRAKE`)
5. El handle debe saltar a B2 en **un** ciclo IPC (~120 ms), no 5 pasos

---

## Tests regresión

```bat
```

---

## Referencia cruzada

| Dastsc | TSW6 |
| --- | --- |
| `nexus-agent/src/brake/planBrake.ts` | `braking/v2/` (`planner.py`, `limit_brake.py`, …) |
| `nexus-agent/src/command/commandBus.ts` | `v2/command.py` |
| `Dastsc-V3/backend/core/command_bus.py` | `tsw_ipc_bus.py` |
| `useAutoCommand.ts` | `autopilot_core.tick` + `HandleController` |
| Horario / paradas | `hud_timetable.py` | [HUD_TIMETABLE.md](HUD_TIMETABLE.md) |
