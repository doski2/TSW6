# Código v2 — dónde va cada pieza

**Plan:** [PLAN_V2.md](PLAN_V2.md) · **Mantenimiento:** [MANTENIMIENTO.md](MANTENIMIENTO.md)

## Regla principal

| Qué | Dónde |
| --- | --- |
| **Proyecto V2 (todo)** | **`V2/`** en la raíz del repo |
| Python producto | `V2/tsw6v2/` |
| Tests producto | `V2/tests/` |
| Legacy autopilot GUI | `tsw6/autopilot/` + `tsw6/braking/v2/__init__.py` (re-export) → `tsw6v2` |
| Orquestación v1 archivada | `archive/braking_v1_autopilot/` (coordinator, policy, station_plan — referencia) |
| Cableado D2 (GetData + IPC) | `V2/tsw6v2/bridge/` — contrato [CANAL_CONTROL](../CANAL_CONTROL.md) |

## Estructura `V2/`

```text
V2/
  README.txt
  run.bat              python -m tsw6v2 …
  run_p1_session.bat   P1 + JSONL + investigate (limit | station | signal | p1)
  test_ipc.bat
  test_pytest.bat
  tsw6v2/
    bridge/              GetData parser + IPC (contrato D2)
    constants.py         umbrales cartel + física producto
    physics.py           v²/2a (paso 3)
    plan.py              BrakePlan / fases UK
    target.py            BrakeTargetResult + tipos plan
    planning.py          GetData cartel + is_ascending_limit_exit + resolve_limit_objective
    limit_state.py       latch BRAKE_LIMIT
    limit_notch.py       escalón B1→B3 + histéresis
    limit_containment.py HOLD_DH + horizonte BRAKE_LIMIT
    limits.py            fachada evaluate_limit_brake
    command.py           APPLY / RELEASE / COAST (paso 3)
    decision.py          tick cartel → BrakeCommand
    loop.py              AgentLoop (~20 Hz)
    autopilot_limit.py   puente speed_decider → evaluate_limit_tick (solo cartel)
    learner.py / brake_air.py
    trace.py / session_report.py
    ipc.py / probe.py / channel.py / diagnostic.py
    gui.py / cli.py / p1_mode.py / p1_layers.py
  tests/
    test_physics.py / test_command.py / test_release.py
    test_decision.py / test_h1_downhill.py / test_learner.py / test_brake_air.py
    test_loop.py / test_trace.py / test_session_report.py
    test_bridge.py / test_ipc.py / test_channel.py / test_probe.py / test_gui.py
    …
```

`tsw6/braking/v2/` — solo `__init__.py` (re-export `LimitP1Adapter` / tipos). Sin shims de física.

## Comandos

```bat
python -m pytest V2/tests/ -q
V2\test_pytest.bat
V2\run_p1_session.bat limit cross-city
V2\run.bat console
V2\run_gui.bat
V2\test_ipc.bat
```

`PYTHONPATH` debe incluir la raíz del repo **y** `V2/` (los `.bat` lo configuran).

## v1 vs V2

| Situación | Qué hacer |
| --- | --- |
| Feature nueva cartel/bajada | Solo `V2/tsw6v2/` + `V2/tests/` |
| Sesión P1 cartel | `V2\run_p1_session.bat` → `decision.evaluate_limit_tick` |
| Autopilot GUI (`iniciar_autopilot.bat`) | FSM estación v1; cartel vía `autopilot_limit` → mismo tick V2 |
| Bug en v1 producción | Arreglo mínimo **o** portar regla a V2 |
| Import desde v1 en `tsw6v2/` | **Prohibido** — contrato D2 en `bridge/` |

## Estado (pasos PLAN_V2)

| Paso | Qué | Estado |
| --- | --- | --- |
| 1 | Contrato GetData | Casi cerrado |
| 2 | Esqueleto `V2/tsw6v2/` | **Cerrado** (pytest + `test-ipc` in-game) |
| **3** | Física / learner / carteles en V2 | **pytest verde** (87 tests `V2/tests/`) · validar in-game `run_p1_session` |

Módulos cartel: `planning` · `limit_state` · `limit_notch` · `limit_containment` · `limits` · `decision` — ver [MANTENIMIENTO § Plan cartel](MANTENIMIENTO.md#plan-cartel-p1-limit_).

**Reglas de frenado:** [REGLAS_FRENOS_P1.md](REGLAS_FRENOS_P1.md). Umbrales mph en `constants.py`: zona vigente **posted+0.5** (`posted_zone_hold_ceiling_mph`); coast **59.5** (`posted_zone_coast_floor_mph`); BRAKE_LIMIT al next **posted−1** (`passenger_ops_target_mph`).

Fases de producto (0–6): [PLAN_V2 § Fases](PLAN_V2.md#fase-0--contrato-io).

## Relacionados

- [README v2](README.md) · [PLAN_V2](PLAN_V2.md)
