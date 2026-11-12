# 0001 — Base nueva desde cero usando V2 como oráculo

- **Estado:** Propuesta
- **Fecha:** 2026-11-12
- **Pregunta de origen:** PREGUNTAS.md § A.1

## Contexto

Análisis del repositorio (2026-11-12, FACT salvo indicado):

- `V2/tsw6v2/`: ~20 200 líneas en 71 módulos; `V2/tests/`: 660 tests pasan (9 saltados) en Linux
  excluyendo `test_gui.py` (necesita tkinter).
- Legacy v1 (`tsw6/` + `tests/`, ~20 300 líneas) convive con V2; `tsw6/governor` y `tsw6/telemetry`
  importan de `tsw6v2`. 1 test legacy falla (`test_hud_timetable`) y 2 no cargan fuera de Windows
  (`ctypes.windll`).
- Sin `pyproject.toml` ni CI; imports dependen de `PYTHONPATH` (`pytest.ini` añade `.` y `V2`).
- Supuestos de la Class 323 en el núcleo: `NEUTRAL_NOTCH`, `B1_NOTCH`, `_BRAKE_HANDLES` aparecen
  47 veces en 10 módulos; física activa como estado global (`physics.set_active_physics`).
- Funciones muy largas: `loop._step_core` 361 líneas, `session_report._render_chart_svg` 321,
  `decision.evaluate_p1_tick` 205 (14 parámetros); `AgentLoop` con 33 campos y 32 métodos.
- Instrucciones de agentes IA triplicadas: `.cursor/`, `.codex/`, `.github/agents`.
- Lo valioso: reglas P1 calibradas con sesiones reales, fixtures de la 323, scripts de
  paridad/replay (`V2/scripts/parity_jsonl.py`, `replay_jsonl.py`, `regression_check.py`).

## Opciones consideradas

1. **Refactor incremental de V2.** Menos riesgo, pero arrastra la forma actual (palanca combinada de
   la 323, bucle monolítico) y es difícil cambiar los cimientos poco a poco.
2. **Reescritura desde cero sin oráculo.** Diseño libre, pero se pierden las reglas calibradas y
   habría que redescubrir los fallos jugando.
3. **Desde cero con oráculo (propuesta).** Arquitectura nueva sin ataduras; el comportamiento de V2
   (logs JSONL + fixtures + tests) es la especificación de partida. El motor nuevo se valida
   reproduciendo esos logs; las diferencias se clasifican como *bug nuevo*, *bug viejo corregido* o
   *mejora intencionada* (con ADR).

## Decisión

Pendiente de debate. Recomendación: opción 3.

## Consecuencias

- V2 se congela (solo arreglos críticos) mientras la base nueva no alcance paridad.
- Hay que construir primero el **arnés de replay/paridad** independiente de ambos motores.
- Los logs de sesiones reales pasan a ser un activo del proyecto: hay que decidir dónde se guardan
  (ver PREGUNTAS § F.3).
