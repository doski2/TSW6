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
| `v2/physics.py` | Cinemática única (distancias, márgenes, **ventana de aplicación**) — ver abajo |

### Ventana de aplicación (2026-08-26)

Los metros de acción del plan **ya no son constantes**. Todo pasa por `physics.py`:

| Función | Uso |
| --- | --- |
| `apply_zone_margin_m(speed_ms, apply_at)` | Zona base: `max(25, speed×2.5, apply_at×0.12)`, cap **150 m** |
| `brake_command_apply_zone_m(...)` | Misma fórmula con `speed_mph` + `apply_at` coherente (`distance − dist_start`) |
| `is_in_brake_action_window(...)` | Ventana simétrica **±zona** — prioridad estación, `station_brake`, bloqueo RELEASE |
| `should_emit_brake_command(...)` | Emitir APPLY: ±zona **o** tarde dentro del envelope (`distance ≤ apply_at`) |

**Ejemplo Class 323 @ 60 mph** (`apply_at ≈ 400 m`): zona ≈ **67 m** (antes 60 m fijo).

**Dos reglas (no confundir):**

| Regla | Función | Cuándo |
| --- | --- | --- |
| ¿Plan en ventana de acción? | `is_in_brake_action_window` | Prioridad, estación gana, `release_blocked:station` |
| ¿Mandar APPLY / COAST_THROTTLE? | `should_emit_brake_command` | Emisión IPC; incluye tarde si aún `distance ≤ apply_at` |

#### Migración: umbrales fijos → física

| Antes (hardcoded) | Ahora | Módulo |
| --- | --- | --- |
| Zona APPLY **60 m** | `apply_zone_margin_m` / `brake_command_apply_zone_m` | `physics.py`, `command.py`, `planner.py` |
| Histeresis cartel **80 m / 30 m** | ±`apply_zone_m` del plan activo | `limit_brake.py` |
| Contención bajada **150 m** al cartel | `distance ≤ apply_zone_margin_m(speed, distance)` | `limit_brake.py` |
| B3 tarde si `dist_start < −30` | `dist_start < −late_zone_m` (`brake_command_apply_zone_m`) | `command.py` |
| RELEASE sin mirar estación | `release_blocked:station` si estación en ventana | `coordinator.py` |

Constantes que **siguen** siendo fijas (no cinemática): `TARGET_CLUSTER_GAP_M = 350`,
`STATION_COAST_CUTOFF_M = 100`, emergencia andén por distancia absoluta en `emergency.py`.

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
