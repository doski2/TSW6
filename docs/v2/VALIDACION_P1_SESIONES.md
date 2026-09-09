# Validación P1 cartel — sesiones Cross-City

**Estado:** protocolo activo (2026-09-09) · **Reglas:** [REGLAS_FRENOS_P1.md](REGLAS_FRENOS_P1.md)

Guía para validar el stack actual en varias sesiones in-game antes de más features.
No sustituye `pytest`; complementa prueba de campo.

---

## Stack congelado (qué validamos)

| Pieza | Módulo |
| --- | --- |
| Prioridad H1 + latch | `limits.py`, `limit_containment.py` |
| Muesca + defer | `limit_notch.py` |
| Feedback decel + aire | `brake_feedback.py`, `brake_air.py` |
| EMA online | `learner.py`, `learner_v1.py` |
| Decisión + IPC | `decision.py`, `loop.py` |
| Trace | `trace.py`, `session_report.py` |

**Fuera de alcance** hasta nueva fase: estación, señal, `limit_planner.py`, COAST_PWR en WATCH.

---

## Antes de cada sesión

```bat
python -m pytest V2/tests/ -q
```

- [ ] Probe instalado · Class 323 · Cross-City (o ruta con 60→55).
- [ ] **Copia de seguridad del perfil** (si vas a aprender online):

```bat
copy logs\profiles\RVM_BCC_WRM_Class323_DMS_A_C.json logs\profiles\RVM_BCC_WRM_Class323_DMS_A_C.bak.json
```

- [ ] Palanca neutro/tracción al arrancar el agente; sin freno manual.

---

## Ejecutar sesión

```bat
V2\run_p1_session.bat limit cross-city
```

Conduce **≥ 5 min** · varios carteles 60→55 y 55→45 · Ctrl+C al cerrar.

Al salir, busca en consola:

```text
perfil -> logs\profiles\....json (fill=..., decel_n=...)
```

Regenerar HTML:

```bat
python scripts\tools\summarize_v2_limit.py logs\v2\ULTIMA.jsonl --html
```

---

## Qué mirar (por sesión)

| Fuente | Comprobar |
| --- | --- |
| **Consola** | `decel_n > 0` solo con frenadas reales; sin errores IPC masivos |
| **Resumen** | `python scripts\tools\summarize_v2_limit.py …jsonl` — APPLY/RELEASE razonables |
| **HTML replay** | Paneles presión + decel; stats FB shortfall; tabla Feedback/aire |
| **JSONL** | Bloques `"fb"` con `a_obs` solo en APPLY; `p1.reason=air_fill` esperable al inicio de freno |
| **Perfil** | `n_bands` sube despacio; no un solo viaje con +200 muestras |

### Criterios “sesión OK” (orientativos)

| Métrica | OK | Revisar |
| --- | --- | --- |
| Pico sobre cartel | ≤ posted + 1 mph (TSW) | > +1.5 mph sostenido |
| HOLD_DH lejos 60→55 | B1 suave, sin P3 subiendo 56→62 | WATCH + tracción larga |
| APPLY al 55 | Antes de ~200 m @ 55 mph | Primer APPLY @ &lt; 150 m muy rápido |
| `fb_escalated` | 0–pocos (aire estable) | Muchos sin subir muesca |
| `air_fill_ticks` | Algunos al meter B1 | Cientos (aire roto / probe) |
| GAP | 0 o bajo | Muchos `command_none` cerca cartel |

---

## Protocolo multi-sesión (3 vueltas)

| # | Objetivo | Notas |
| --- | --- | --- |
| **1** | Línea base con perfil actual | Anotar `fb_shortfall`, puntualidad 60→55 |
| **2** | Misma ruta tras aprendizaje | ¿Baja shortfall? ¿EMA estable? |
| **3** | Tramo distinto (más 55→45) | Perfil banda 30–60 vs 60+ |

Entre sesiones: **no borrar** JSONL (comparar con `compare_sessions.bat` o diff manual).

Si el perfil diverge mucho en sesión 1: restaurar `.bak.json` y repetir con filtro aire (post 2026-09-09).

---

## Falsos positivos y fallos conocidos

| Síntoma | Probable causa | ¿Bug? |
| --- | --- | --- |
| Muchos `fb.shortfall`, 0 `escalated` | Shortfall 1 tick, no 2 seguidos; o regla bajada (+2 mph) | A menudo no |
| `fb` vacío en APPLY | `P < 92 %` muesca o `lever ≠ handle` (lag IPC) | No — filtro aire |
| `decel_n` muy alto en 1 sesión | Aprendió transitorios (sesión pre-filtro aire) | Corregido; restaurar perfil |
| EMA B1 muy bajo (~0.24) | Una sesión agresiva | Restaurar backup; validar 2–3 sesiones |
| `ack_timeout` en log UE4SS | IPC puntual | Secundario si mandos llegan |
| HOLD_DH + WATCH mezclados en estado | Deuda `limit_planner` (dos histéresis/tick) | Conocido, bajo impacto lejos |
| Sin `accel_ms2` en probe | Campo HUD ausente | Feedback/EMA inactivos — revisar probe |
| `air_ready` con `P=None` | Probe sin cilindro | Modo degradado: APPLY sin gate P |

---

## Código depurado (no usar / eliminado)

| Item | Estado |
| --- | --- |
| `should_coast_throttle_before_brake` | **Eliminado** — COAST en `decision.py` + `command.py` |
| `is_in_brake_action_window` | Reservado estación/señal; cartel usa `is_in_apply_zone` |
| `archive/braking_v1_autopilot/` | Solo referencia histórica |
| Orquestación v1 en `tsw6/autopilot/` | GUI usa `tsw6v2.autopilot_limit` |

---

## Cuando escalar (abrir issue / tuning)

- Pico **> 62 mph** sostenido antes de 55 en bajada (tras fix WATCH/HOLD).
- `fb_escalated` frecuente y aún tarde al cartel.
- Perfil `ema_bands` monotono bajando sin estabilizar en 3 sesiones.
- `GAP` > 50 ticks cerca cartel.

---

## Relacionados

- [REGLAS_FRENOS_P1.md](REGLAS_FRENOS_P1.md) — reglas y constantes
- [MANTENIMIENTO.md](MANTENIMIENTO.md) — checklist P3 y probe
- [p1_limit_capas.html](p1_limit_capas.html) — diagrama capas
