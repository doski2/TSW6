# Validación P1 — sesiones Cross-City (cartel + andén)

**Estado:** protocolo activo (2026-09-10) · **Reglas:** [REGLAS_FRENOS_P1.md](REGLAS_FRENOS_P1.md)

Guía para validar el stack actual en varias sesiones in-game antes de más features.
No sustituye `pytest`; complementa prueba de campo.

| Modo | Comando | Qué valida |
| --- | --- | --- |
| **Cartel** | `V2\run_p1_session.bat limit cross-city` | Paso 3 — límites 60→55, RELEASE, learner |
| **Andén** | `V2\run_p1_session.bat station cross-city` | P1 estación + HTTP `DriverAid.TrackData` (§ abajo) |

---

## Stack congelado (qué validamos)

| Pieza | Módulo |
| --- | --- |
| Prioridad H1 + latch | `limits.py`, `limit_containment.py`, `limit_horizon.py` |
| Muesca + defer + coast trim | `limit_notch.py`, `command.py` (`coast_trim_deferred`) |
| Feedback decel + aire | `brake_feedback.py`, `brake_air.py` |
| EMA online | `learner.py`, `learner_v1.py` |
| RELEASE cinemático (BRAKE_LIMIT) | `physics.py`, `command.py` |
| Decisión + IPC | `decision.py`, `loop.py` |
| Trace | `trace.py`, `session_report.py` |
| Andén (modo `station`) | `station_plan`, `station_brake`, `p1_policy`, `limit_station_cluster`, `planning_poller` |
| Señal roja (paso 5) | `signal_plan`, `signal_brake`, `service_brake`, `p1_emergency` |
| FSM dwell andén | `p1_station_gate` — suprime P1 en `STOPPED`/`DEPARTING` |
| Replay sesión | `session_report.py` — HTML con zoom, puertas, marcadores APPLY |

**Fuera de alcance** hasta nueva fase: dwell puertas completo (paso 7), `limit_planner.py`,
COAST_PWR en WATCH cartel, filtro `tsw_hud.db` en planning V2, aprendizaje por distancia integrada
(solo EMA tick a tick con filtro aire), latch probe `signal_red` (pérdida ~40 m en marcha).

**Paso 5 (2026-09-13):** `evaluate_signal_brake` — plan gradual v→0 + emergencia. Validación
in-game pendiente (sesión ref. `225433Z`).

---

## Antes de cada sesión

```bat
```

- [ ] Probe instalado · Class 323 · Cross-City (o ruta con 60→55).
- [ ] **Copia de seguridad del perfil** (si vas a aprender online):

```bat
```

- [ ] Palanca neutro/tracción al arrancar el agente; sin freno manual.
- [ ] **Modo `station`:** TSW6 con `-HTTPAPI` · `CommAPIKey.txt` presente · servicio con paradas en

  `data\timetable.json` (p. ej. headcode `2R17`).

---

## Ejecutar sesión (cartel)

```bat
```

Conduce **≥ 5 min** · varios carteles 60→55 y 55→45 · Ctrl+C al cerrar.

Al salir, busca en consola:

```text
```

Regenerar HTML (si hace falta):

```bat
```

---

## Qué mirar (por sesión)

| Fuente | Comprobar |
| --- | --- |
| **Consola** | `decel_n > 0` solo con frenadas reales; sin errores IPC masivos |
| **Resumen** | `python scripts\tools\summarize_v2_limit.py …jsonl` — APPLY/RELEASE razonables |
| **HTML replay** | Paneles presión + decel; stats FB shortfall; tabla Feedback/aire; sección **Señal (rojo)** si hubo ticks rojos |
| **JSONL** | Bloques `"fb"` con `a_obs_ms2` en APPLY con aire; `p1.reason=air_fill` al inicio de freno; `signal_red`/`signal_dist_m` si pasas semáforo rojo |
| **Consola investigate** | `sig=ROJO@…m` cuando probe emite rojo |
| **Perfil** | `n_bands` sube despacio (+20–40/sesión larga OK); `decel_n` en consola al cerrar |
| **RELEASE** | Bajada: ~55–56 mph proyectado; llano/subida: `spd ≤ objetivo + 0.4` (no undershoot a 44 en 60→50) |

### Criterios “sesión OK” (orientativos)

| Métrica | OK | Revisar |
| --- | --- | --- |
| Pico sobre cartel | ≤ posted + 1 mph (TSW) | > +1.5 mph sostenido |
| HOLD_DH lejos 60→55 | B1 suave, sin P3 subiendo 56→62 | WATCH + tracción larga |
| APPLY al 55 | Antes de ~200 m @ 55 mph | Primer APPLY @ &lt; 150 m muy rápido |
| `fb_escalated` | 0–pocos (aire estable) | Muchos sin subir muesca |
| `air_fill_ticks` | Algunos al meter B1 | Cientos (aire roto / probe) |
| GAP | 0 o bajo | Muchos `command_none` cerca cartel |
| `decel_n` al cerrar | 20–80 en sesión ≥10 min con frenadas | 0–5 (aire/bombeo) |
| 1er APPLY 60→55 | HOLD_DH ~700 m si pico ~60.4 | `plan` ~500 m sin HOLD_DH |
| 45→60 en subida | COAST sin B1; sin HOLD_DH | B1 @ 55 mph en P6; sin `sig=` si probe viejo |
| 70→45 caída grande | Primer APPLY ≥ B2 si ≥18 mph de caída | Atascado en B1 con P ~1.6 bar |
| Señal rojo salida | `signal_red` en JSONL + HTML | Solo HUD; consola sin `sig=` |
| Rojo lejos en marcha | `p1tgt=SIGNAL`, `COAST_PWR` o plan; no solo `no_plan` | 0 plan con rojo @ &gt;500 m |
| Aproximación rojo | `p1tgt=SIGNAL` (no HOLD_DH cartel); parada antes del poste | SPAD; emergencia solo @ &lt;60 m |
| Salida andén, cartel 35 @ &gt;3 km | `p1tgt` vacío, capa OK, P6 permitido en zona 60 | `p1tgt=LIMIT` + Vigilar o `COAST_PWR` lejos |
| HOLD_DH zona 15 en bajada | `RELEASE` tras ~14–15 mph; no B1 hasta 6 mph | 0 `RELEASE` en JSONL; `reason=no_plan` con B1 |

### Referencia (sesiones Cross-City guardadas)

| JSONL | Notas |
| --- | --- |
| `20260908T215743Z` | Mucho `a_obs` pre-filtro aire agresivo — restaurar perfil si EMA raro |
| `20260908T222629Z` | Poco aprendizaje (8 muestras); bombeo; sin HOLD_DH |
| `20260908T225707Z` | Mejor línea base: HOLD_DH, ~27 muestras limpias, `decel_n` modesto |
| `20260912T183116Z` | **Antes fix:** 70→45 atascado B1 @ ~1.6 bar — **tras fix:** B2 mínimo, umbral 1.55 bar |
| `20260912T201456Z` | **Antes fix:** P6 @ 55 sin coast + HOLD_DH uphill 45→60 — **tras fix:** coast trim + sin HOLD en subida |
| `20260912T221258Z` | **Antes fix:** salida andén, cartel 35 @ 4 km → `COAST_PWR` / Vigilar — **tras fix:** `no_plan`, sin `p1tgt`, tracción en zona 60 |
| `20260912T224046Z` | **Antes fix:** HOLD_DH @ 15 mph en bajada, 0 RELEASE, B1 hasta ~6 mph — **tras fix:** RELEASE con `pick=None` y andén lejos |
| `20260912T225433Z` | **Antes fix:** SPAD rojo (solo emergencia @ 61 m; HOLD_DH @15 en final) — **tras fix paso 5:** plan SIGNAL desde lejos; validar in-game |

---

## Protocolo multi-sesión (3 vueltas)

| # | Objetivo | Notas |
| --- | --- | --- |
| **1** | Línea base con perfil actual | Anotar `fb_shortfall`, puntualidad 60→55 |
| **2** | Misma ruta tras aprendizaje | ¿Baja shortfall? ¿EMA estable? |
| **3** | Tramo distinto (más 55→45) | Perfil banda 30–60 vs 60+ |

Entre sesiones: **no borrar** JSONL (comparar con `compare_sessions.bat` o diff manual).

Si el perfil diverge mucho en sesión 1: restaurar `.bak.json` y repetir con filtro aire (post
2026-09-09).

---

## Falsos positivos y fallos conocidos

| Síntoma | Probable causa | ¿Bug? |
| --- | --- | --- |
| Muchos `fb.shortfall`, 0 `escalated` | Shortfall 1 tick, no 2 seguidos; o regla bajada (+2 mph) | A menudo no |
| `fb` vacío en APPLY | `P < 92 %` muesca o `lever ≠ handle` (lag IPC) | No — filtro aire |
| `decel_n` muy alto en 1 sesión | Aprendió transitorios (sesión pre-filtro aire) | Corregido; restaurar perfil |
| EMA B1 muy bajo (~0.24) | Una sesión agresiva | Restaurar backup; validar 2–3 sesiones |
| `ack_timeout` en log UE4SS | IPC puntual | Secundario si mandos llegan |
| HOLD_DH + WATCH mezclados en estado | Mitigado con snapshots en `limits.py` (2026-09-12) | Revisar si reaparece |
| Rojo en HUD, no en JSONL | Probe sin reinstalar tras cambio Lua | Re-ejecutar `install_ue4ss_probe.bat` |
| Sin `accel_ms2` en probe | Campo HUD ausente | Feedback/EMA inactivos — revisar probe |
| `air_ready` con `P=None` | Probe sin cilindro | Modo degradado: APPLY sin gate P |
| RELEASE ~55 mph y luego ~54 | RELEASE cinemático (proyección `fill`) | No — comportamiento esperado |
| `decel_n` bajo con sesión larga | Bombeo B1↔costa; poco tiempo con P≥92 % | Tuning futuro; seguir validando |
| B1 tras HOLD_DH en modo `station` | Antes 2026-09-13: RELEASE no corría con `pick=None` | Corregido — validar `RELEASE` en replay |
| SPAD con `signal_red` lejos | Antes paso 5: solo emergencia tardía + HOLD_DH final | Plan SIGNAL; validar `225433Z` in-game |
| `signal_red` desaparece @ ~40 m | Probe pierde aspecto en marcha | Latch Lua; anotar sesión |

---

## Código depurado (no usar / eliminado)

| Item | Estado |
| --- | --- |
| `should_coast_throttle_before_brake` | **Eliminado** — COAST en `decision.py` + `command.py` |
| `is_in_brake_action_window` | Reservado estación/señal; cartel usa `is_in_apply_zone` |
| `archive/braking_v1_autopilot/` | Solo `station_plan` + `objectives` (ref. estación) |
| `tsw6/autopilot/` (GUI) | Cartel vía `tsw6v2.autopilot_limit`; FSM estación legacy |

---

## Cuando escalar (abrir issue / tuning)

- Pico **> 62 mph** sostenido antes de 55 en bajada (tras fix WATCH/HOLD).
- `fb_escalated` frecuente y aún tarde al cartel.
- Perfil `ema_bands` monotono bajando sin estabilizar en 3 sesiones.
- `GAP` > 50 ticks cerca cartel.

---

---

## Validación P1 andén — modo `station` + HTTP (tarjeta C2 parcial)

Objetivo: confirmar que `stn=` baja con marcha, `p1tgt=STATION` al acercarte, y frenada v→0 sin
regresión de cartel. **No** valida puertas ni dwell (paso 7).

### Prerrequisitos

| # | Comprobar | Cómo |
| --- | --- | --- |
| 1 | HTTPAPI activo | TSW6 arrancado con `-HTTPAPI`; puerto `31270` responde |
| 2 | Clave API | `%USERPROFILE%\Documents\My Games\TrainSimWorld6\Saved\Config\CommAPIKey.txt` |
| 3 | Servicio en marcha | Horario cargado (Cross-City 2R17 u otro en `data\timetable.json`) |
| 4 | Probe + F7 | GetData con `speed`, `dist_limit`, palanca |
| 5 | pytest local | `V2\test_pytest.bat` verde (~600 tests) |

**Fallback sin HTTP** (solo laboratorio): escribe distancia manual y repite la checklist de
`stn=` / `p1tgt=`:

```bat
```

### Arranque

```bat
```

Debe aparecer en stderr:

```text
```

Si dice `Planning.txt (manual o fallback…)` → no hay HTTP; revisar `-HTTPAPI` y clave antes de
cerrar la validación.

### Tramo recomendado (Cross-City 323)

1. Salir de Lichfield / tramo con **próxima parada programada** (Four Oaks, Sutton, etc.).
2. Conducir **≥ 3 min** acercándote a una parada del horario.
3. Incluir un tramo con **cartel + andén** (p. ej. 60→55 antes de Sutton) para probar

   `pick_p1_brake_target`.

4. Llegar a **v ≈ 0** en el andén (parada completa).
5. Ctrl+C tras la parada o al salir del andén.

### Qué mirar en consola (`--investigate`)

| Campo | OK | Revisar |
| --- | --- | --- |
| `stn=` | Número positivo que **baja** con marcha (saltos ~2 s HTTP + suave entre ticks) | Siempre `—` |
| `stn=` tras pausa | No baja en parado prolongado | Sigue bajando parado |
| `p1tgt=` | `LIMIT` lejos; `STATION` al entrar en horizonte de servicio | Nunca `STATION` con `stn>2000` |
| `fsm=` | Vacío en marcha; `STOPPED` en andén parado; `DEPARTING` tras cerrar puertas | `fsm=STOPPED` en toda la ruta con `spd>25` (gate atascado — ver § gate) |
| `lim=` + `p1tgt=LIMIT` | Cartel gana si Four Oaks (gap > 50 m) u overspeed en cluster | `LIMIT` con cartel 50 **tras** andén (< 50 m) y `stn<700` |
| `p1tgt=STATION` + cartel tras andén | `lim@` un poco mayor que `stn` (p. ej. +27 m) → **STATION** desde ~700 m | `SPEED_LIMIT` APPLY al cartel 50 ignorando parada |
| `p1tgt=STATION` bajo cartel | spd ≤ posted+0.9 y proyección al pasar cartel legal → STATION fijo | Oscilación STATION↔LIMIT con spd~52 y lim 55 |
| `p1=APPLY` + `p1tgt=STATION` | Antes del andén, muesca coherente con velocidad | Sin APPLY con `stn<30` y spd>15 |
| `ipc_tgt=` | Muesca IPC pendiente (0–8) | — |
| Parada final | `spd` → 0–2 mph; sin overshoot fuerte | Pasar andén >5 mph |

Ejemplo de secuencia esperada:

```text
```

### Qué mirar en JSONL / HTML

- [ ] Líneas con `station_dist_m` o `stn` en investigate coherente con distancia HUD (orden de

  magnitud; fin de plataforma, no tablón fino).

- [ ] Al menos un tick con `p1tgt=STATION` (JSONL: `p1_tgt`) antes de la parada.
- [ ] Sin ráfagas de `command_none` (`GAP`) todo el tramo final si `stn<150`.
- [ ] `Planning.txt` en `%TEMP%\TSW6Bridge\` se actualiza si HTTP activo (última línea con

  `station_dist_m=`).

### Criterios “sesión andén OK”

| # | Criterio | Notas |
| --- | --- | --- |
| 1 | HTTP como fuente | AVISO menciona `DriverAid.TrackData`, no solo fallback archivo |
| 2 | `stn=` vivo | ≥ 2 refrescos HTTP visibles (salto + deriva `v×dt`) en tramo ≥ 1 km |
| 3 | Transición LIMIT→STATION | Documentada en log si hubo cartel; con spd bajo el next, `p1tgt=STATION` estable (sin ping-pong) |
| 4 | Parada | Velocidad < 3 mph con `stn` < 50 m (o tras pasar 0) |
| 5 | Sin regresión cartel | Si solo cartel en tramo previo, comportamiento igual que modo `limit` |
| 6 | pytest | `V2\test_pytest.bat` sigue verde tras la sesión |

### Falsos positivos / deuda conocida

| Síntoma | Probable causa | ¿Bug? |
| --- | --- | --- |
| `stn=—` con HTTP | Servicio sin match en `timetable.json` | Ajustar headcode / paradas en JSON |
| Parada de la vía contraria en HTTP | Marker equivocado | Filtro HUD/geo pendiente (§4.6 PLAN) |
| `stn` salta cada ~2 s | Refresh HTTP normal | No |
| `stn` deriva vs HUD | Solo `v×dt` entre polls | Conocido; C2 `odo_m` |
| `p1tgt=STATION` muy lejos | `should_defer_station_brake` falló | Revisar dist/velocidad |
| Freno al cartel en Sutton/Four Oaks | `station_waits` prioriza LIMIT (recorte invertido, gap > 50 m) | Caso Four Oaks — anotar tramo |
| Cartel 50 justo tras andén | `p1tgt=LIMIT` con `lim@` ≈ `stn` + 20–50 m | Sesión `213010Z` — regla `limit_sign_beyond_station` |
| `fsm=STOPPED` toda la sesión | Salida sin puertas; gate no liberó P1 andén | Sesión `210853Z` — `_left_platform` |
| `p1tgt` alterna STATION/LIMIT cada tick | Cartel APPLY con spd ya bajo next; sin proyección | Revisar `will_be_below_limit_at_pass` (sesión 231617Z) |

### Protocolo mínimo (2 sesiones andén)

| # | Objetivo | Ruta sugerida |
| --- | --- | --- |
| **S1** | HTTP + `stn=` + parada limpia | Lichfield → Four Oaks o Sutton |
| **S2** | Cartel + andén mismo tramo | Repetir S1 o tramo con 60→55 antes del andén |

Guardar JSONL en `logs\v2\` con etiqueta `station` en el nombre. Comparar:

```bat
```

### Cuando escalar (andén)

- `stn=` siempre `—` con HTTP confirmado y servicio en marcha.
- `p1tgt=STATION` con `stn` > 3000 m de forma estable.
- Overshoot habitual > 5 mph en andén conocido (2 sesiones seguidas).
- P1 frena cartel 60→55 cuando `station_waits` debería aplazar (Four Oaks, gap > 50 m).
- Cartel inmediatamente tras andén y `p1tgt=LIMIT` de forma estable (última parada Cross-City).

### Sesiones de referencia (2026-09-10)

| Sesión | Síntoma | Fix / regla |
| --- | --- | --- |
| `210853Z` | `fsm=STOPPED` permanente; sin frenado andén; cartel 50 → ~44 mph | Gate `_left_platform`; RELEASE llano sin cinemática |
| `213010Z` | Última parada: `LIMIT` al 50 tras andén en vez de `STATION` | `limit_sign_beyond_station` + `LIMIT_AFTER_STATION_MAX_M` |

---

## Relacionados

- [REGLAS_FRENOS_P1.md](REGLAS_FRENOS_P1.md) — reglas y constantes
- [MANTENIMIENTO.md](MANTENIMIENTO.md) — checklist P3 y probe
- [p1_limit_capas.html](p1_limit_capas.html) — diagrama capas
- [PLAN_V2.md §4.4](PLAN_V2.md#44-estaciones--andén-tablón) — planning HTTP y deuda C2
