# Paridad Dastsc — TSW6 ↔ Dastsc

**Objetivo:** mismo comportamiento de frenado que `C:\Users\doski\Dastsc` (nexus-agent + commandBus + IPC).

Trabajo en paralelo: cambios de algoritmo en Dastsc se portan aquí; cambios de probe/TSW API solo en TSW6.

---

## Arquitectura Dastsc (referencia)

```text
TelemetrySnapshot
  → planBrake (límite / estación / señal)
  → selectUrgentBrakePlan
  → resolveSuggestedAction (commandBus)
  → buildBrakeCommand(B2) → SendCommand ThrottleAndBrake:-0.5
```

**Sin** COAST/BRAKE genéricos en P1: el plan devuelve **B1/B2/B3** y el bus escribe el **notch absoluto**.

---

## Estado TSW6 (2026-08-23)

### ✅ Hecho

| Pieza | TSW6 | Dastsc |
| --- | --- | --- |
| IPC GetData/SendCommand | `tsw_ue4ss_reader`, `tsw_ipc_bus` | SendCommand.txt |
| Plan límite B1–B3 | `brake_planner.py` | `planBrake.ts` |
| Comando notch directo P1 | `brake_command.py` + `HandleController` IPC | `commandBus.buildBrakeCommand` |
| **RELEASE al objetivo** | `brake_release.py` | `resolveReleaseAction` |
| **Anti-rebrake (coast latch)** | `BrakeReleaseState` | `shouldInhibitLimitRebrake` |
| GUI fase plan | `B2 →N2` en barra Acción | horizon UI |
| Emergencias P1 | P1-CRITICO / EMERGENCIA | similar |
| P2 overspeed / ACK / FSM | `speed_decider.py` | (parcial en agent) |
| **Horario HUD (planning)** | `hud_timetable.py` + `tsw_hud.db` | `schedule.ts` (parcial) |
| **Paradas `car_stop_signs`** | Distancia planning (`hud_geo`) | — |

### 🔄 En curso / siguiente

| Pieza | Prioridad |
| --- | --- |
| `planBrakeForStation` + `selectStationActiveStep` | **Alta** (parada exacta) |
| Recalcular distancia tablón cada tick (GPS) | Media |
| `shouldBlockAutoReleaseForStation` — no soltar en andén | Media |
| `planBrakeForSignal` (DANGER) | Media |
| `selectUrgentBrakePlan` cluster estación+límite | Media |
| Horario — reaction scale / coast allowance | Media |
| Perfil por tren (`agent_config` JSON) | Media |
| Freight split-brake (throttle + train_brake) | Baja (SD40-2) |
| Modos SUGGEST / ARM / AUTO | Baja (GUI) |

### TSW6 extra (no en Dastsc brake module)

- SafetyWatchdog exceso persistente
- Marcador freno DMI advisory
- FSM estación UK (puertas, OCR, creep)
- Solo-frenado (sin ACCELERATE automático)

---

## Pipeline P1 actual (post-paridad ejecución)

```text
DriverAid dist/límite (probe)
  → brake_planner.plan_for_speed_limits
  → brake_command.plan_to_brake_command  →  B2, notch=2
  → HandleController._apply_combined_notch  →  IPC PowerBrakeHandle 0.25
  → SendCommand.txt
```

P2 / emergencia / sin plan activo: sigue COAST/BRAKE/HARDBRAKE escalonado (teclado fallback).

---

## Cómo validar in-game

1. `install_ue4ss_probe.bat` + reiniciar GUI
2. Acercarse a límite más bajo con tracción manual
3. En **Depuración**: `P1 PLAN … B2 … → B2 notch=2`
4. En **Acción**: `B2 →N2` (no solo `BRAKE`)
5. El handle debe saltar a B2 en **un** ciclo IPC (~120 ms), no 5 pasos

---

## Tests regresión

```bat
python -m pytest test_brake_command.py test_brake_planner.py test_handle_controller.py test_speed_decider.py test_hud_timetable.py -q
```

---

## Referencia cruzada

| Dastsc | TSW6 |
| --- | --- |
| `nexus-agent/src/brake/planBrake.ts` | `brake_planner.py` |
| `nexus-agent/src/command/commandBus.ts` | `brake_command.py` |
| `Dastsc-V3/backend/core/command_bus.py` | `tsw_ipc_bus.py` |
| `useAutoCommand.ts` | `autopilot_core.tick` + `HandleController` |
| Horario / paradas | `hud_timetable.py` | [HUD_TIMETABLE.md](HUD_TIMETABLE.md) |
