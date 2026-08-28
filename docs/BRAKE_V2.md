# Frenado P1 v2

**Activo en autopilot** desde `SpeedDecider` → `BrakeCoordinatorV2`.

Todo el código de frenado está en **`tsw6/braking/v2/`** (sin `archive/braking_v1/`).

---

## Módulos

| Archivo | Rol |
| --- | --- |
| `v2/coordinator.py` | Un tick P1: RELEASE, emergencias, prioridad, latch unificado |
| `v2/policy.py` | Dónde: cluster 350 m, parada unificada, qué objetivo gana |
| `v2/objectives.py` | Cómo: andén (`station_plan`), señal stub, emergencia |
| `v2/station_plan.py` | Perfil parada HUD: B1–B3 a 0, ETA, sin OCR |
| `v2/limit_brake.py` | Cartel de velocidad (perfil + física latched) |
| `v2/command.py` | `BrakeTargetResult`, APPLY / RELEASE, anti-rebrake |
| `v2/plan.py` | Tipos `BrakePlan`, `BrakePlanStep` |
| `v2/physics.py` | Cinemática (distancias, márgenes, ventana de aplicación) |

### Ventana de aplicación (2026-08-26)

Los metros de acción del plan **ya no son constantes**. Todo pasa por `physics.py`:

| Función | Uso |
| --- | --- |
| `apply_zone_margin_m(speed_ms, apply_at)` | Zona base: `max(25, speed×2.5, apply_at×0.12)`, cap **150 m** |
| `brake_command_apply_zone_m(...)` | Misma fórmula con `speed_mph` + `apply_at` coherente (`distance − dist_start`) |
| `is_in_brake_action_window(...)` | Ventana simétrica **±zona** — prioridad estación, andén, bloqueo RELEASE |
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
| Zona APPLY **60 m** | `apply_zone_margin_m` / `brake_command_apply_zone_m` | `physics.py`, `command.py` |
| Histeresis cartel **80 m / 30 m** | ±`apply_zone_m` del plan activo | `limit_brake.py` |
| Contención bajada **150 m** al cartel | `distance ≤ apply_zone_margin_m(speed, distance)` | `limit_brake.py` |
| B3 tarde si `dist_start < −30` | `dist_start < −late_zone_m` (`brake_command_apply_zone_m`) | `command.py` |
| RELEASE sin mirar estación | `release_blocked:station` si estación en ventana | `coordinator.py` |

Constantes que **siguen** siendo fijas (no cinemática): `TARGET_CLUSTER_GAP_M = 350`,
`STATION_COAST_CUTOFF_M = 100`, emergencia andén por distancia absoluta en `objectives.py`.

Import público: `from tsw6.braking import BrakeCoordinatorV2`

---

## Flujo (un tick)

```text
1. RELEASE  — cartel en banda (≤ target+0.4) y andén fuera de horizonte de servicio
2. Emergencia  — andén / señal roja (P1-CRITICO)
3. Candidatos  — SPEED_LIMIT / STATION (si no diferida) / SIGNAL
4. Prioridad   — distancia en vía + cluster 350 m
5. Comando     — command_from_target → COAST | RELEASE | APPLY → IPC
```

`should_defer_station_brake`: no hay B1 de andén hasta `station_dist > horizonte(v→0) + 25 m`
(decel de servicio, no la ventana gorda B1).

---

## Parada unificada (2026-08-27)

Una sola regla en `policy.py` (`is_unified_limit_station_stop`): cartel antes del andén,
gap ≤ 350 m, y **no** cabe frenar a v_límite, soltar y luego parar.

| Qué | Quién | No hacer |
| --- | --- | --- |
| **Cuándo** APPLY cartel | SPEED_LIMIT si `spd > límite + 0.9` | B1 de andén a 800 m |
| **Coast / RELEASE** | Cartel hecho (`spd ≤ límite + 0.4`) | Dejar B1 pegado hasta el andén |
| **Cuándo APPLY andén** | STATION cuando entra horizonte de servicio | Usar apply_at de B1 (~1,1 km) |
| Sustituir cartel por estación | dist al cartel **≤ 8 m** | `dist_start` de B1 estación negativo desde lejos |

Logs: `p1cmd=RELEASE` tras el 55; `p1tgt=STATION` cerca del andén; `uni=Y`.

### Prioridad (resto)

1. **Distancia en vía** — el objetivo más cercano por delante, salvo cluster.
2. **Dos fases** (sí cabe parar tras el cartel) → cartel primero; estación en coast (`should_delay_unified_station_plan`).
3. **Señal detrás del andén** (≤50 m o mismo cluster) → descartar señal.

Constantes: `TARGET_CLUSTER_GAP_M = 350`, `STATION_STOPPED_MPH = 1.5`,
`LIMIT_RELEASE_MAX_OVER_MPH = 0.4`, `LIMIT_SCORING_MAX_OVER_MPH = 0.9`.

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
| Telemetría señal DANGER → `evaluate_signal_brake` | Stub |
| OCR distancia tablón en coordinador | No integrado |
| `station_eta` en coordinator (horario) | ✅ vía `TrainState.next_stop_arrival` |
| Tests P1 integración | `test_brake_v2.py`, `test_brake_coordinator.py`, `test_speed_decider.py` |

---

## Tests

```bat
```

Física/policy: `tests/test_brake_planner.py`. Estación: `tests/test_brake_station.py`.
