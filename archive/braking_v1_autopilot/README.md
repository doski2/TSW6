# Braking v1 autopilot (archivado)

Orquestación P1 legacy eliminada del árbol activo (2026-09-06).

| Archivo | Sustituto |
| --- | --- |
| `coordinator.py` | `V2/tsw6v2/autopilot_limit.py` + `decision.py` |
| `policy.py` | `tsw6/governor/limit_station_cluster.py` (FSM) |
| `station_plan.py` | `tsw6/autopilot/station_eta.py` (solo ETA); parada P1 pendiente V2 |
| `objectives.py` | — (estación/señal P1 no migrado) |
| `command.py`, `physics.py`, `plan.py`, `limit_brake.py` | `V2/tsw6v2/` |

Sesiones cartel: `V2\run_p1_session.bat`.
