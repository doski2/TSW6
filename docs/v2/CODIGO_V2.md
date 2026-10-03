# Código v2 — dónde va cada pieza

**Plan:** [PLAN_V2.md](PLAN_V2.md) · **Mantenimiento:** [MANTENIMIENTO.md](MANTENIMIENTO.md) · **P1:** [REGLAS_FRENOS_P1.md](REGLAS_FRENOS_P1.md)

## Regla principal

| Qué | Dónde |
| --- | --- |
| **Proyecto V2 (todo)** | **`V2/`** en la raíz del repo |
| Python producto | `V2/tsw6v2/` |
| Tests producto | `V2/tests/` |
| Legacy autopilot GUI | `tsw6/autopilot/` + `tsw6/braking/v2/__init__.py` (re-export) → `tsw6v2` |
| Orquestación v1 archivada | `archive/braking_v1_autopilot/` (coordinator, policy, station_plan — referencia) |
| Cableado D2 (GetData + IPC) | `V2/tsw6v2/bridge/` — contrato [CANAL_CONTROL](../CANAL_CONTROL.md) |
| Perfil tren (IPC MC) | `data/vehicles/*.json` — `brake_input` 0..1; resolver `vehicle_package.py` |

## Estructura `V2/`

```text
V2/
  tsw6v2/          # producto Python (cartel, andén, señal, loop, IPC)
  tests/           # pytest producto (~370 tests; ver MANTENIMIENTO)
  scripts/         # replay JSONL, write_planning.txt, etc.
  run_p1_session.bat
```

`tsw6/braking/v2/` — solo `__init__.py` (re-export `LimitP1Adapter` / tipos). Sin shims de física.

## Comandos

```bat
cd V2
set PYTHONPATH=..;.
python -m pytest tests/ -q
V2\run_p1_session.bat limit cross-city
V2\run_p1_session.bat station cross-city
```

`PYTHONPATH` debe incluir la raíz del repo **y** `V2/` (los `.bat` lo configuran).

Perfil de deceleración: `logs/profiles/<vehicle>.json` (auto al arrancar sesión si existe; ver
[MANTENIMIENTO § Perfil learner](MANTENIMIENTO.md#perfil-learner-logsprofiles)).

## v1 vs V2

| Situación | Qué hacer |
| --- | --- |
| Feature nueva cartel/bajada | Solo `V2/tsw6v2/` + `V2/tests/` |
| Sesión P1 cartel / andén | `V2\run_p1_session.bat limit\|station` → `AgentLoop` + `evaluate_p1_tick` |
| Planning andén sin HTTP | `V2\scripts\write_planning.py <metros>` → `%TEMP%\TSW6Bridge\Planning.txt` |
| Legacy GUI v1 (`iniciar_autopilot.bat`) | No usar en producto v2 |
| Bug en v1 producción | Arreglo mínimo **o** portar regla a V2 |
| Import desde v1 en `tsw6v2/` | **Prohibido** — contrato D2 en `bridge/` |

## Estado (pasos PLAN_V2)

| Paso | Qué | Estado |
| --- | --- | --- |
| 1 | Contrato GetData | Casi cerrado |
| 2 | Esqueleto `V2/tsw6v2/` | **Cerrado** (pytest + `test-ipc` in-game) |
| **3** | Física / learner / P1 cartel + andén en V2 | **pytest verde** (`V2/tests/`, ~370) · `run_p1_session` limit/station |

### Módulos cartel (orden de lectura)

| Módulo | Rol |
| --- | --- |
| `planning.py` | GetData; `large_zone_to_next_drop`; **`zone_hold_suppressed_for_ascending_exit`** (H1 salida ascendente); `is_ascending_limit_exit` |
| `limit_horizon.py` | Horizonte BRAKE_LIMIT; caída grande 90→15 extendida |
| `limit_state.py` | Latch; `zone_posted_mph` al enganchar |
| `limit_notch.py` | Muesca B1–B3; defer; `_early_large_drop_b1_apply` |
| `limit_containment.py` | HOLD_DH / zone_contain (`pick_downhill_containment`) |
| `limits.py` | `evaluate_limit_brake` (dual snapshot HOLD vs BRAKE_LIMIT) |
| `physics.py` | `should_emit_brake_command`; **`speed_limit_horizon_commit`** |
| `command.py` | COAST / APPLY / RELEASE |
| `decision.py` | `evaluate_p1_tick`; `_overlay_active_zone_hold` |
| `trace.py` | JSONL sesión |

Andén / prioridad: `station_plan` · `station_brake` · `p1_policy` · `limit_station_cluster` ·
`p1_station_gate` · `planning_poller` · `session_report` — ver
[MANTENIMIENTO § Plan cartel](MANTENIMIENTO.md#plan-cartel-p1-limit_) y
[REGLAS_FRENOS_P1 §9](REGLAS_FRENOS_P1.md#9-prioridad-cartel--andén-dos-objetivos).

**Distancia andén (una fuente de verdad):**

| Símbolo | Módulo | Uso |
| --- | --- | --- |
| `station_within_dwell_zone` | `station_plan` | ≤ `dwell_max_distance_m` (80 m): no defer horizonte (`p1_policy`), `allow_watch` en dwell (`decision`). |
| `station_distance_for_brake_plan` | `station_brake` | Entrada única a `evaluate_station_brake` y cheque STATION en emergencia (`decision`): telemetría ≤0 con marcha → `STATION_OVERSHOOT_PLAN_DISTANCE_M` (1 m). |
| `STATION_COAST_CUTOFF_M` | `physics` | STATION en ventana: no `COAST_THROTTLE` si dist ≤ 100 m (`command`). |

**IPC MC (M3a):** wire = `mc_service_brake_fraction` (interp. `neutral`↔`B3` en `brake_input`); bucle `loop._mc_ramp_ipc_fraction` + `MC_IPC_FRACTION_STEP`; feedback/release `probe_mc_input_fraction` (no `train_brake` HUD). Claves `B1`/`B2` en JSON son referencia lab — el cable usa solo extremos + intensidad P1.

`evaluate_station_brake` sigue rechazando `distance_m ≤ 0`; no llamarlo con geo cruda tras el marcador.

**Reglas de frenado:** [REGLAS_FRENOS_P1.md](REGLAS_FRENOS_P1.md) — tabla «Ventanas y puertas» (no duplicar
`_in_apply_window` / `should_emit` / `zone_hold_suppressed` / `speed_limit_horizon_commit`).

Umbrales mph en `constants.py`: techo zona `posted_zone_hold_ceiling_mph`; coast
`posted_zone_coast_floor_mph`; BRAKE_LIMIT al next `passenger_ops_target_mph`; salida ascendente
`ASCENDING_EXIT_COAST_POSTED_MAX_MPH` (35) vs zonas lentas `ASCENDING_EXIT_ZONE_HOLD_MIN_POSTED_MPH` (30).

Fases de producto (0–6): [PLAN_V2 § Fases](PLAN_V2.md#fase-0--contrato-io).

## Relacionados

- [README v2](README.md) · [VALIDACION_P1_SESIONES](VALIDACION_P1_SESIONES.md)
