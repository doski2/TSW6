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
```

`tsw6/braking/v2/` — solo `__init__.py` (re-export `LimitP1Adapter` / tipos). Sin shims de física.

## Comandos

```bat
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
| **3** | Física / learner / P1 cartel + andén en V2 | **pytest verde** (~198 tests `V2/tests/`) · `run_p1_session` limit/station |

Módulos cartel: `planning` · `limit_state` · `limit_notch` · `limit_containment` · `limits` ·
`decision`. Andén: `station_plan` · `station_brake` · `p1_policy` · `limit_station_cluster` ·
`planning_poller` (HTTP `DriverAid.TrackData` + fallback `Planning.txt`) — ver
[MANTENIMIENTO § Plan cartel](MANTENIMIENTO.md#plan-cartel-p1-limit_) y
[REGLAS_FRENOS_P1 §9](REGLAS_FRENOS_P1.md#9-prioridad-cartel--andén-dos-objetivos).

**Reglas de frenado:** [REGLAS_FRENOS_P1.md](REGLAS_FRENOS_P1.md). Umbrales mph en `constants.py`:
zona vigente **posted+0.5** (`posted_zone_hold_ceiling_mph`); coast **59.5**
(`posted_zone_coast_floor_mph`); BRAKE_LIMIT al next **posted−1** (`passenger_ops_target_mph`).

Fases de producto (0–6): [PLAN_V2 § Fases](PLAN_V2.md#fase-0--contrato-io).

## Relacionados

- [README v2](README.md) · [PLAN_V2](PLAN_V2.md)
