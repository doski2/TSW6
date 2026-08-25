# Frenado P1 v2

**Activo en autopilot** desde `SpeedDecider` → `BrakeCoordinatorV2`.

Todo el código de frenado está en **`tsw6/braking/v2/`** (sin `archive/braking_v1/`).

---

## Módulos

| Archivo | Rol |
| --- | --- |
| `v2/coordinator.py` | Orquestación P1: RELEASE, emergencias, prioridad, latch unificado |
| `v2/limit_brake.py` | Cartel de velocidad (perfil + física latched) |
| `v2/station_brake.py` | Parada en andén → `planner.plan_brake_for_station` |
| `v2/planner.py` | Planificación Dastsc (límite, estación, horario, cluster) |
| `v2/signal_brake.py` | Semáforo rojo (stub — falta telemetría DANGER) |
| `v2/priority.py` | Qué objetivo gana (orden en vía + cluster 350 m) |
| `v2/cluster.py` | Cartel ↔ estación, parada unificada, coast cartel→andén |
| `v2/emergency.py` | P1-CRITICO / P1-EMERGENCIA (andén y señal roja) |
| `v2/types.py` | `BrakeTargetResult` → `BrakeCommand` |
| `v2/command.py` | Notch IPC, RELEASE, anti-rebrake (coast latch) |
| `v2/plan.py` | Tipos `BrakePlan`, `BrakePlanStep` |
| `v2/physics.py` | Cinemática única (distancias, márgenes) — ver [FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md) |

Import público: `from tsw6.braking import BrakeCoordinatorV2`

---

## Flujo

```text
```

Antes del plan activo: `resolve_release_command` y `check_p1_emergency`.

---

## Prioridad (resumen)

1. **Distancia en vía** — el objetivo más cercano por delante gana salvo reglas de cluster.
2. **Cluster cartel + andén (≤350 m)** — si no cabe frenar al cartel y parar después → **parada

   unificada** (solo estación).

3. **RELEASE en cartel** — en parada unificada, soltar a ~velocidad del cartel y coast hacia andén

   (`should_delay_unified_station_plan`).

4. **Cartel redundante** — si `speed ≤ limit + 1.5 mph` → gana estación.
5. **Señal detrás del andén** (≤50 m o mismo cluster) → descartar señal.

Constantes: `TARGET_CLUSTER_GAP_M = 350`, `STATION_STOPPED_MPH = 1.5`,
`LIMIT_RELEASE_MAX_OVER_MPH = 0.5`.

---

## Acciones del decider (`control_actions.py`)

| Acción | Significado | Ejecución |
| --- | --- | --- |
| `HOLD` | No tocar mando | — |
| `COAST` | Soltar tracción | Teclado / IPC |
| `BRAKE` | Un paso de freno servicio | Teclado fallback |
| `BRAKE_FAST` | Freno servicio máximo (hasta B3), ciclos cortos | DMI, watchdog |
| `EMERGENCY` | Muesca 0 ATP (P1-CRITICO ≤25 m) | `BrakeCommand` + IPC |
| `RELEASE` | Neutro tras objetivo | `BrakeCommand` |

P1 activo: la muesca va en `BrakeCommand`; `action` suele ser `HOLD`.

Sin capa P2: si P1 no tiene plan el decider devuelve `HOLD`. Ver [ESTADO § Sin
P2](ESTADO.md#sin-p2-2026-08-25).

Física y calibración: [FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md).

## Integración autopilot

```python
```

Propiedades usadas por GUI: `last_brake_command`, `last_debug` (`p1_debug`).

---

## Pendiente

| Tema | Estado |
| --- | --- |
| Telemetría señal DANGER → `signal_brake` | Stub |
| OCR distancia tablón en coordinador | No integrado |
| `station_eta` en coordinator (horario) | ✅ vía `TrainState.next_stop_arrival` |
| Tests P1 integración | `test_brake_v2.py`, `test_brake_coordinator.py`, `test_speed_decider.py` |

---

## Tests

```bat
```

Planner y estación: `tests/test_brake_planner.py`, `tests/test_brake_station.py` (importan
`tsw6.braking.v2.planner`).
