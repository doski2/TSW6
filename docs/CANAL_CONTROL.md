# Canal de control — plan de fases

Documento de arquitectura para corregir el cuello de botella IPC/mandos antes de
retomar trabajo en P1, learner o planner.

**Última revisión:** 2026-08-26
**Relacionado:** [FLUJO_FRENOS.md](FLUJO_FRENOS.md) · [ESTADO.md](ESTADO.md) ·
`probe_latencia.bat` · `tsw6/telemetry/control_latency_probe.py`

---

## Diagnóstico (resumen)

| Síntoma en log | Causa real |
| --- | --- |
| `hz=427` en heartbeat | **No** es frecuencia del bucle — es `1/mean(tick_work)` |
| `tgt=10Hz` | Objetivo real del bucle Python (GUI usa 20 Hz tras Fase A) |
| `tick=2787ms` | Bucle **bloqueado** esperando ACK IPC síncrono |
| `IPC falló` + `KEY notch 4→3` | Fallback teclado **incremental** vs plan **absoluto** |
| `age=10s` `seq` congelado | Bucle colapsado; telemetría no se lee |
| `ipc=OK` en cycle | Significa “mandó este tick”, no “ACK OK” |
| `handle_notch` | Derivado de HUD Power, no palanca real tras `InputValue` |

---

## Fase 0 — Instrumentación (hecho / en curso)

| ID | Tarea | Estado |
| --- | --- | --- |
| 0.1 | `control_latency_probe.py` + `probe_latencia.bat` | ✅ |
| 0.2 | Penalización IPC 300 s → 5 s + reintentos | ✅ |
| 0.3 | Heartbeat honesto: `loop_hz`, `work_ms`, `sleep_ms` | 🔄 Fase A |
| 0.4 | Documento de fases (este archivo) | ✅ |

**Criterio de aceptación Fase 0:** probe en juego vivo con p95 round-trip &lt; 200 ms y
&gt; 95 % ACK OK en secuencia `4,3,2,1,4`.

---

## Fase A — Canal no bloqueante (implementación activa)

Separar **lectura**, **escritura** y **decisión** en ritmos distintos.

```text
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ TelemetryReader │     │ AsyncCommandWriter│     │ ControlLoop     │
│ hilo 20 Hz      │     │ hilo + cola       │     │ 20 Hz (GUI)     │
│ lee GetData.txt │     │ IPC + ACK         │     │ decide + encola   │
│ snapshot atómico│     │ nunca bloquea tick│     │ nunca espera ACK  │
└────────┬────────┘     └────────┬─────────┘     └────────┬────────┘
         │                       │                          │
         └───────────────────────┴──────────────────────────┘
                    TswTelemetrySource + CommandState
```

| ID | Tarea | Archivos |
| --- | --- | --- |
| A.1 | `TelemetryReader` — hilo 20 Hz, lectura GetData | `tsw6/telemetry/control_channel.py` |
| A.2 | `AsyncCommandWriter` — cola IPC, ACK en hilo aparte | `tsw6/telemetry/control_channel.py` |
| A.3 | Integrar en `TswTelemetrySource` | `tsw_telemetry_source.py` |
| A.4 | `HandleController` encola mandos (no bloquea) | `handle_controller.py` |
| A.5 | Heartbeat: `loop_hz` `work_ms` `sleep_ms` `cmd_q` `ack_ms` | `autopilot_core.py` |
| A.6 | Lua: `lever_notch` + `last_cmd_id` en GetData | `mods/.../main.lua` |
| A.7 | Parser probe: `lever_notch`, priorizar sobre HUD | `tsw_ue4ss_reader.py` |
| A.8 | Tests unitarios canal | `tests/test_control_channel.py` |
| A.9 | GUI/consola `loop_hz=20` alineado con Lua | `autopilot_gui.py`, `tsw_autopilot.py` |

**Criterio de aceptación Fase A:**

- 0 ticks con `work_ms > 150 ms` por bloqueo IPC en bucle normal
- `loop_hz` real ≥ 18 Hz con juego a 50+ FPS
- Cola de mandos drena sin caída a teclado en P1 (configurable)

---

## Fase B — IPC robusto

| ID | Tarea |
| --- | --- |
| B.1 | `ack_timeout` adaptativo (2–4 frames @ FPS actual) |
| B.2 | Correlación `cmd_id` en ACK y GetData |
| B.3 | Sin fallback teclado en P1 (`BrakeCommand`); fail loud + métricas |
| B.4 | Reintento en cola (no penalizar canal entero) |
| B.5 | (Opcional) socket/pipe en lugar de archivos |

---

## Fase C — Planner sincronizado con actuador

El plan no avanza de fase hasta confirmar muesca o timeout explícito.

| ID | Tarea |
| --- | --- |
| C.1 | `CommandState.reached_notch` en FSM P1 |
| C.2 | RELEASE solo si `distance_next_m` &gt; umbral **y** velocidad ≤ objetivo |
| C.3 | Eliminar ventanas `sin_plan_activo` al pasar cartel |
| C.4 | Watchdog no compite con cola IPC saturada |

---

## Fase D — Telemetría completa

| ID | Tarea |
| --- | --- |
| D.1 | `brake_cyl_bar` fiable en probe (Class 323) |
| D.2 | `probe_raw` distancia fiable o deprecar en logs |
| D.3 | Resumen de sesión al cerrar autopilot |

---

## Métricas de log (nuevo formato heartbeat)

```text
heartbeat loop_hz=19.8 work=8ms sleep=42ms tgt=20Hz
  cmd_q=0 ack=18ms last_id=42 lever=3 hud=3 match=Y
  spd=45.2 lim=60 age=35ms seq=1842 telem_poll=20Hz
```

| Campo | Significado |
| --- | --- |
| `loop_hz` | Frecuencia real del bucle (ticks/s en ventana 2 s) |
| `work_ms` | Tiempo de `tick()` sin sleep |
| `sleep_ms` | Sleep hasta próximo tick |
| `telem_poll` | Hz del `TelemetryReader` |
| `ack_ms` | Último ACK IPC en hilo escritor |
| `lever` / `hud` | Muesca palanca real vs HUD Power |
| `match` | `lever == target` del último mando |

---

## Orden de trabajo

1. **Fase A** — sin esto, no tocar planner/learner
2. Validar con `probe_latencia.bat` en juego
3. **Fase B** — endurecer IPC
4. **Fase C** — lógica P1
5. **Fase D** — telemetría auxiliar

---

## Comandos útiles

```bat
```
