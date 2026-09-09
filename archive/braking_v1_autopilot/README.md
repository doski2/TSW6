# Braking v1 autopilot (archivado)

Orquestación P1 legacy eliminada (2026-09-10). **No ejecutar en producción.**

| Eliminado | Sustituto activo |
| --- | --- |
| `coordinator.py` | `V2/tsw6v2/decision.py` + `autopilot_limit.py` |
| `policy.py` | `tsw6/governor/limit_station_cluster.py` (FSM GUI) |
| `command.py`, `physics.py`, `plan.py`, `limit_brake.py` | `V2/tsw6v2/` |

**Conservado** (referencia pasos 6–7 estación/señal; imports `tsw6v2`):

| Archivo | Uso |
| --- | --- |
| `station_plan.py` | Perfil parada andén (ETA, distancia HUD) |
| `objectives.py` | `evaluate_station_brake`, stub señal roja |

Cartel P1: `V2\run_p1_session.bat` · reglas [docs/v2/REGLAS_FRENOS_P1.md](../../docs/v2/REGLAS_FRENOS_P1.md).
