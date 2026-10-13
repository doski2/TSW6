# Análisis del proyecto V2 — 2026-10-13

Alcance: `V2/tsw6v2/` (59 módulos, ~15.8 k líneas). Sin cambios de código en este análisis.
Evidencia clasificada según `00-tsw6-core.mdc`: FACT = código leído; INFERENCE = deducción; UNKNOWN
= no demostrado.

## 1. Tamaño y complejidad (FACT)

Archivos más grandes (líneas):

| Líneas   | Archivo              | Nota                                                    |
| -------- | -------------------- | ------------------------------------------------------- |
| 1526     | `session_report.py`  | HTML + cálculo; candidato a partir (render vs métricas) |
| 1125     | `decision.py`        | Núcleo P1; ya concentra mucha lógica                    |
| 926      | `loop.py`            | Bucle agente; envío IPC + estado                        |
| 891      | `p1_station_gate.py` | FSM de estación                                         |
| 752      | `vehicle_package.py` | Datos de vehículo                                       |
| 713      | `station_plan.py`    |                                                         |
| 711      | `command.py`         |                                                         |
| 695      | `gui.py`             |                                                         |

## 2. Duplicados (FACT)

- **`DEFAULT_ACK_TIMEOUT_S` definido dos veces**: `ipc.py:25` (0.35) y `loop.py:58` (alias de

  `AGENT_ACK_TIMEOUT_S`). Ambos valen 0.35 hoy, pero es una fuente de verdad duplicada. Riesgo:
  divergencia futura.

- **Timeouts por defecto inconsistentes**: `ipc.py` (funciones `dispatch_*`) y `bridge/ipc_bus.py`

  usan `ack_timeout_s=0.12` por defecto, mientras el agente usa 0.35 y el diagnóstico
  `IPC_ACK_TIMEOUT_S` (0.35). Una sola constante debería gobernar todo.

- **`PredictDecelFn` redefinido en 7 módulos** (`autopilot_limit`, `command`, `decision`,

  `limit_state`, `plan`, `signal_brake`, `station_brake`). Debe existir una sola definición (p. ej.
  `learner_v1` o `constants`).

- **`main` en 2 módulos**: normal (puntos de entrada), sin acción.

## 3. Fallos y riesgos (FACT salvo indicado)

- **ACK ok sin confirmar palanca** (`loop.py`, `_notch_step_pending`): si el ACK es `ok` el

  pendiente no se activa, y el paso puede reenviarse si la palanca tarda en cambiar. Hueco conocido,
  bajo riesgo observado (5 cambios de palanca en 1547 ticks en 214529Z).

- **Excepciones amplias** (`except Exception`): `hud_schedule.py:64,76` y `planning_poller.py:361`.

  Ocultan errores; conviene registrar y tratar la causa.

- **Ventana de aprendizaje de 2 s** (`learn_quality.py`): cualquier cambio de muesca descarta la

  ventana entera (`notch_unstable`). Limita el aprendizaje de `mixed` (16 rechazos en 214529Z).
  Cambio de diseño pendiente de confirmación.

- **Rama MC y rama combinada** comparten `_brake_kind`/aprendizaje pero con tablas distintas; el

  riesgo es confusión de tablas (ya tratado con `brake_kind` explícito).

## 4. Mejoras propuestas (INFERENCE)

1. Unificar `DEFAULT_ACK_TIMEOUT_S` y los `ack_timeout_s=0.12` en `constants.py`, y usar una sola

   referencia en `ipc.py`, `ipc_bus.py` y `loop.py`.

2. Mover `PredictDecelFn` a un único módulo y reexportarlo desde los demás.
3. Sustituir los `except Exception` por excepciones concretas, o registrar con `logging` antes de

   continuar.

4. Partir `session_report.py` en: métricas (sin HTML) y render HTML.
5. Confirmar la ventana de 2 s: reiniciar solo desde el último tick válido en lugar de borrar todo.
6. Cerrar el hueco del ACK ok: marcar pendiente también con ACK ok hasta que la palanca confirme el

   cambio.

## 5. Pendiente de validación (UNKNOWN)

- Efecto real del pendiente de paso sobre la palanca en campo (solo 1 sesión evaluada).
- Si `v1_mixed` converge con varias sesiones limpias.
- Regla de 300 m de llegada/DEPARTING: sin segunda parada en campo.

## 6. Orden sugerido de trabajo

1. Unificar constantes de timeout (bajo riesgo, mejora de mantenibilidad).
2. Unificar `PredictDecelFn` (bajo riesgo).
3. Revisar `except Exception` (riesgo de ocultar fallos).
4. Cerrar hueco ACK ok (lógica de control; requiere validación).
5. Decidir ventana de aprendizaje (diseño; requiere confirmación).
6. Partir `session_report.py` (refactor grande; hacerlo aparte).
