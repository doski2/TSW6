# Reglas de frenos P1 — diseño V2 desde cero

**Estado:** diseño acordado (2026-09-04) · **H1** implementado · tuning campo 2026-09-12
**Plan:** [PLAN_V2.md](PLAN_V2.md) · **Código:** [CODIGO_V2.md](CODIGO_V2.md)

---

## Política (no negociable)

| Sí | No |
| --- | --- |
| Diseñar reglas en `V2/tsw6v2/` con tests + JSONL | Copiar orquestación v1 (`archive/braking_v1_autopilot/`) |
| Tomar de v1 solo **ideas** validadas (física, capas, UK 323) | Heredar capas paralelas legacy (contención ×3, prioridades opacas) |
| Cada regla: motivo + capa trace + test | Paridad ciega con v1 “porque antes estaba” |
| Perfeccionar con sesiones Cross-City | Ampliar `tsw6/autopilot/` ni `tsw6/braking/` |

**v1** (`archive/braking_v1_autopilot/`) = **referencia histórica** para producto nuevo.

---

## Qué conservamos de v1 (solo ideas)

Ideas que **sí** entran en el diseño V2 — reimplementadas, no pegadas.

### 1. Física única

- Una distancia: **`s = (v² − u²) / (2a_eff)`** (+ margen reacción + fill aire).
- **`a`** de learner si hay perfil (`logs/profiles/<vehicle>.json`, auto-carga en sesión); si no,

  fracciones B1/B2/B3 UK.

- Pendiente: **una vez** — en `a` aprendida **o** en `g` en la fórmula, nunca las dos.
- TSW penaliza **> límite + 1 mph** → en plan usamos **+0,9 mph** sobre el cartel **vigente** (techo

  de scoring).

- El cartel **siguiente** (BRAKE_LIMIT) usa **−1 mph** sobre su posted (UK pasajeros).

### 2. Dos techos mph (no mezclar)

| Capa | Intención | Fórmula | Ej. zona 60, next 55 |
| --- | --- | --- | --- |
| **Zona vigente** — HOLD_DH, contención bajada | No superar el límite **actual** en bajada | `posted + zone_hold_over(grad)` | **60.2** @ −1 %% / **60.5** suave |
| **Cartel siguiente** — BRAKE_LIMIT (latch) | Llegar al **next** con margen UK | `posted_next − 1` | **54** (cartel 55) |
| **Penalización TSW** (histéresis / scoring) | Límite duro juego | `posted + 0.9` | **60.9** |

Código (`constants.py`):

| Función | Uso |
| --- | --- |
| `posted_zone_hold_ceiling_mph(posted)` | Techo HOLD_DH / contención (60→**60.5**) |
| `posted_zone_coast_floor_mph(posted)` | Suelo coast tras contener (60→**59.5**) |
| `posted_scoring_ceiling_mph(posted)` | Penalización TSW (60→60.9) |
| `passenger_ops_target_mph(posted)` | Solo BRAKE_LIMIT al cartel siguiente |
| `downhill_ops_coast_ceiling_mph(posted)` | Defer BRAKE_LIMIT (= techo zona 60.5) |

**Prioridad** en `evaluate_limit_brake` (`limits.py`):

1. **BRAKE_LIMIT** con `apply_now` → gana (dentro del horizonte del next o en ventana apply).
2. **Contención bajada** (`pick_downhill_containment`) si superas el techo de la zona vigente.
3. **BRAKE_LIMIT** en WATCH (lejos, bajo techo de zona) — solo calcula; **no** bloquea HOLD_DH.

**Evaluación dual (2026-09-12):** BRAKE_LIMIT y HOLD_DH se calculan sobre **copias**
(`LimitBrakeState.snapshot()`); solo la ruta ganadora hace `replace_from` al estado vivo. El learner
solo observa decel en la ruta BRAKE_LIMIT comprometida — evita latch/EMA contaminados por la rama
perdedora (sesión `201456Z`).

**Horizonte cinemático:** `limit_horizon.py` — `next_limit_brake_horizon_m` /
`within_next_brake_horizon` (fuente única; antes duplicado en contención y `limits`).

**Defer** (`limit_notch.downhill_defer_brake_commit`): no comprometer B1 todavía si aún vas legal en
la zona vigente. Usa `next_brake_overrides_zone_hold` para no diferir dentro del horizonte ni en la
banda de acercamiento (56–62.2 mph @ zona 60 @ −1 %%). Esa función **no** participa en la prioridad
de `limits.py` (fix sesión 20260908T210357Z).

**Caso 60→55 en bajada** (tests: `test_h1_downhill.py`, `test_coast_trim.py`):

| Velocidad | Dist. al cartel 55 | Modo | Objetivo |
| --- | --- | --- | --- |
| ≤ techo zona (60.2 @ −1 %% / 60.5 suave) | Lejos (> horizonte) | WATCH | — |
| > techo zona | Lejos | HOLD_DH / zone_contain | **60.2** / **60.5**, B1 suave; RELEASE ~**59.5** |
| Cualquiera | ≤ horizonte | BRAKE_LIMIT | **54**, B1 primero; escalar solo cerca de 54+2 mph |

Excepciones:

- **60→55**: contención @ techo zona (**60.2** @ −1 %%, **60.5** suave) fuera del horizonte; soltar

  en **59.5** si hay presión/coast eficiente (solo **fuera** del horizonte hacia el 55).

- **55→45** (y bajada con cartel next **bajando**): RELEASE al cartel next en **ops+0.5** (45→**44.5**);

  no arrastrar B1 hasta ~40; no soltar por `eff_floor` de zona vigente **dentro** del horizonte.

- **Subida de cartel en bajada** (10→30, 15→50): RELEASE en suelo zona vigente (**ops+0.5**)

  lejos del next **o** en horizonte si la velocidad está en banda de la zona lenta (sesiones

  `081745Z`, `142034Z`). No usar ops del cartel siguiente (anti-parado).

- **60→60** (misma zona): HOLD_DH si `spd >` techo zona.
- **45→60** (subida de límite en **cuesta**): sin HOLD_DH ni zone_contain — dejar acelerar

  (`is_ascending_limit_exit` + `is_uphill_gradient`; sesión `201456Z`). En llano/bajada la regla
  `should_skip_zone_hold_for_ascending_exit` sigue aplicando.

- **70→45** (caída grande): en ventana APPLY, `pick_weakest` exige **mínimo B2** si

  `speed − target ≥ BRAKE_PLAN_LARGE_DROP_MPH` (18 mph); primer compromiso usa la muesca elegida,
  no B1 forzado (sesión `183116Z`).

### 2b. Coast trim en subida

Cuando `downhill_defer_brake_commit` difiere el APPLY (vas legal en zona vigente pero el plan del
next existe), `limits.py` marca `coast_trim_deferred=True` en `BrakeTargetResult`.

| Pendiente | Comportamiento |
| --- | --- |
| **Bajada** | Defer solo — COAST_PWR cuando entras en horizonte pre-coast |
| **Subida** | `command_from_target`: **COAST_THROTTLE** aunque `dist_start` esté lejos del horizonte pre-coast (`early_coast`) |

Caso típico: 45→60 @ +1 %%, P6 con tracción @ 55 mph — soltar gas antes del cartel sin frenar
(sesión `201456Z`). Tests: `test_coast_trim.py`.

**Excepción caída grande en subida (60→35):** si `posted − next ≥ BRAKE_PLAN_LARGE_DROP_MPH` (18) y
vas **legal en zona vigente** (p. ej. 56 mph en zona 60) **fuera del horizonte** del cartel 35, **no**
diferir coast-trim comparando con ops del next (34 mph). Evita `COAST_THROTTLE` a 4 km al salir del
andén (sesión `221258Z`). Sigue aplicando en 60→55 @ +1 %% (caída posted &lt; 18).

### 3. Objetivos claros por tick

Cada tick el planificador elige **un modo** (no una pila de `if` legacy):

| Modo | Intención |
| --- | --- |
| **NONE** | Sin cartel / sin plan |
| **WATCH** | Cartel lejos; calcular pero no mandar |
| **HOLD_DH** | Bajada: sujetar **zona vigente** (`posted + 0.9`) hasta horizonte del **siguiente** cartel |
| **BRAKE_LIMIT** | Frenar al **siguiente** cartel (`posted_next − 1`; latch + muesca mínima) |
| **RELEASE** | En banda; soltar (con excepciones bajada) |
| **COAST_PWR** | Quitar tracción antes de freno |
| **SIGNAL** | Semáforo rojo: plan gradual v→0 (`evaluate_signal_brake`; paso 5) |

### 4. Muescas UK pasajeros

- Servicio B1→B3 (handle 3→1); **un escalón por tick** (IPC + aire).
- Elegir la **más débil que basta**; subir si tarde o corto de distancia.
- Emergencia (notch 0) solo pegado al objetivo.

### 5. Aire (L4 lite)

- No APPLY sin presión; no bombar tras soltar; escalón acorde a `brake_cyl_bar`.
- Depende de probe — sin presión, modo degradado documentado.
- Class 323: umbral nominal B1 ~**1.55 bar** (`PRESSURE_BRAKING_MIN_BAR`,

  `brake_air.pressure_for_handle`). Con muesca de servicio ya aplicada, `air_ready` exige

  **92 %** de la presión esperada para esa muesca (`pressure_for_handle × 0.92` ≈ 1.43 bar en

  B1) — evita `air_fill` con cilindro ~1.51 bar en HOLD_DH (sesión `143544Z`).

### 6. Trazabilidad

- Cada decisión → `p1.reason` + capa (`p1_layers`) + JSONL para debatir tuning.
- JSONL incluye `signal_red` / `signal_dist_m` si el probe los emite; consola investigate:

  `sig=ROJO@…m` (`trace.py`). Replay HTML: sección **Señal (rojo)** (`session_report.py`).

### 7. Feedback decel cerrado (bucle corto)

Compara **decel medida** (`accel_ms2` del probe, signo invertido) con el **perfil aprendido**
(`predict_decel` / learner) en la muesca comprometida.

| Condición | Acción |
| --- | --- |
| Ventana APPLY + muesca comprometida (B1/B2) | Medir cada tick |
| `a_obs < 0.70 × a_pred` | Contador `weak_decel_ticks` +1 |
| 2 ticks seguidos con shortfall | Un escalón B1→B2→B3 (`decel_feedback`) |
| Misma regla bajada que histéresis | Solo escalar si `spd ≤ ops_next + 2 mph` |
| Cualquier escalón (histéresis o feedback) | Reset `weak_decel_ticks` — **un escalón/tick** |

**No** aplica en HOLD_DH / WATCH (solo ruta `BRAKE_LIMIT` en `limits._evaluate_next_limit_brake`).

**Dos vías de escalada** (complementarias, no duplicadas):

| Vía | Trigger | Módulo |
| --- | --- | --- |
| **Plan / overspeed** | `spd > ops + 0.65` o pick pide muesca más fuerte | `apply_notch_hysteresis` |
| **Feedback** | Decel real < 70 % del perfil, 2 ticks | `apply_weak_decel_feedback` |

JSONL: bloque `fb` (`a_pred_ms2`, `a_obs_ms2`, `shortfall`, `escalated`). Trace: `p1.reason =
decel_feedback` si escala por feedback. Replay HTML: paneles presión + decel y tabla **Feedback
decel / aire**.

**Presión de aire (L4):** sí en **decisión** (`air_ready` bloquea APPLY, `cap_escalation` limita
escalón, `inhibit_reapply` anti-bombeo, `observe_air` → `brake_fill_s`). **Feedback y EMA** solo
miden/aprenden si `brake_decel_sample_ready`: palanca = muesca comprometida y `P ≥ 92 %` de la
presión esperada (`brake_air.pressure_for_handle`).

Constantes (`brake_feedback.py`): `DECEL_SHORTFALL_RATIO=0.70`, `WEAK_DECEL_TICKS=2`,
`DECEL_MIN_PRED_MS2=0.15`, `DECEL_MIN_OBS_MS2=0.08`.

Tests: `V2/tests/test_brake_feedback.py`.

**Perfil vs reacción:** el perfil learner da `a` por muesca (+ `brake_fill_s` en distancia).
`LIMIT_REACTION_S` (1.5 s) es margen **separado** en el latch — no se resta del feedback.

**Aprendizaje online (sesión P1):** en ventana APPLY con muesca comprometida, cada tick con
`accel_ms2` de freno actualiza `ema_bands` / `ema` (α=0.10, igual v1). Al cerrar
`run_p1_session.bat`:

```text
```

Solo si hubo muestras válidas (`decel_n > 0`) o ajuste de aire. No aprende en WATCH/HOLD_DH.

Con filtro aire (post 2026-09-09), `decel_n` modesto (20–80 en sesión larga) es normal; no esperar
cientos por viaje. Validación campo: [VALIDACION_P1_SESIONES.md](VALIDACION_P1_SESIONES.md).

### 8. RELEASE cinemático (BRAKE_LIMIT)

Simétrico al APPLY: no solo banda fija en mph al llegar al objetivo.

| Modo | Cuándo suelta | Criterio |
| --- | --- | --- |
| **Contención zona** (60→55 lejos) | ~59.5 mph | Banda fija `spd ≤ coast_floor + release_over` |
| **BRAKE_LIMIT bajada** (latch al 54) | Antes de 54 mph si el fill seguiría frenando | `v_proy = v + a_net·brake_fill_s ≤ target + banda` |
| **BRAKE_LIMIT llano/subida** | En banda al objetivo | `spd ≤ target + release_over` (sin proyección anticipada) |

- `a_net`: `accel_ms2` del probe si hay frenado; si no, `predict_decel` del learner (**ya incluye

  pendiente** — no volver a sumar `g`).

- `brake_fill_s`: del perfil / `BrakeAirTracker`.
- En bajada cerca del cartel, `should_hold_limit_brake_downhill` no bloquea el latch final (`spd ≤

  latch + 2 mph`).

- **Llano/subida** (`gradient_pct ≥ −0.3 %%`): `limit_release_speed_ready` **no** usa proyección

  cinemática — evita soltar demasiado pronto y caer por debajo del objetivo (sesión `210853Z`,

  60→50 @ +1 %%: RELEASE @ 51 mph → ~44 mph). En **bajada** se mantiene el RELEASE anticipado.

Módulos: `physics.projected_speed_mph_after_brake_fill`, `physics.limit_release_speed_ready`,
`command.resolve_release_command`. Tests: `test_release.py` (kinematic +
`test_no_kinematic_release_uphill_60_to_50`).

**No planificado (2026-09-10):** aprendizaje por distancia de parada integrada u observación en
HOLD_DH — seguir EMA tick a tick hasta estabilizar perfil en campo.

#### RELEASE en modo `station` (2026-09-13)

`evaluate_p1_tick` **siempre** evalúa `resolve_release_command` si hay freno puesto (B1–B3),
**antes** de devolver `no_plan` cuando `pick_p1_brake_target` devuelve `None`.

| Capa | Regla |
| --- | --- |
| `_limit_release_allowed` | Modo cartel: siempre. Modo station: sí salvo `target=STATION` o `station_target.apply_now` |
| `pick=None` + andén lejos | Aún RELEASE de HOLD_DH / BRAKE_LIMIT (sesión `224046Z`: B1 tras zona 15 en bajada −1.7 %%) |
| Sesión `123139Z` | Con `target=STATION` y freno de andén activo → **no** RELEASE de cartel |
| `_overlay_active_zone_hold` | `p1tgt=STATION`/`SIGNAL` WATCH pero HOLD_DH activo → **mando** HOLD_DH; objetivo HUD sin cambio (`173809Z`) |

Orden en `decision.py`: emergencia → planes cartel/andén/señal (pick) → **RELEASE** → overlay HOLD_DH → idle / APPLY / COAST.

**Undershoot:** si se pierde la ventana de RELEASE y la velocidad cae mucho por debajo del
objetivo (`speed < target − LIMIT_RELEASE_MIN_SPEED_BAND_MPH`), el guard anti-parado en escenario
puede mantener B1 — no ampliar sin nueva sesión tras validar el fix `224046Z`.

### 9. Prioridad cartel ↔ andén (dos objetivos)

Modo `station`: cada tick hay hasta **dos planes** (`evaluate_limit_brake` +
`evaluate_station_brake`);
`pick_p1_brake_target` (`p1_policy.py`) elige **uno** para P1. Cluster: cartel **antes** del andén
con gap ≤ `TARGET_CLUSTER_GAP_M` (350 m).

```text
```

| Regla | Cuándo | Objetivo |
| --- | --- | --- |
| `should_defer_station_brake` | Andén más lejos que `bd(v→0)` servicio + 10 m | Sin STATION todavía |
| `_active_limit_or_none` | Andén diferido + cartel solo WATCH | `pick` → `None` (no `p1tgt` fantasma; sesión `221258Z`) |
| `station_waits_for_approach_limit` | Recorte HUD invertido (gap > 50 m) o overspeed al cartel en cluster | LIMIT primero |
| `limit_sign_beyond_station` | Cartel **detrás** del marker (`lim@` > `stn`) | No esperar cartel; priorizar andén |
| `merged_approach_overspeed` | Cluster, cartel **delante** del andén, spd > next + 0.5 | LIMIT |
| `should_prefer_station_in_approach` | Andén < 600 m (o cartel tras andén < 950 m), spd > 15 mph | **STATION** |
| `station_may_ignore_limit_approach` | Cartel delante en cluster + proyección legal | **STATION** anticipado |
| `_ignorable_limit_on_deferred_approach` | Andén diferido + cartel WATCH next ignorable (&lt;600 m) | No `pick` LIMIT (164240Z: 50 tras zona 15) |
| `should_allow_station_watch_when_deferred` | Misma geometría + `should_defer_station_brake` | `evaluate_station_brake(allow_watch=True)` → STATION WATCH |
| `_resolve_deferred_station_pick` | Rama unificada andén diferido | LIMIT APPLY/WATCH o STATION WATCH; no duplicar ramas |

#### Cartel justo **después** del andén (sesión `213010Z`)

Geometría: andén @ 700 m, cartel 50 @ 727 m (zona vigente 60). El cartel **no** es objetivo de

parada — hay que frenar al **marker de andén** primero; el 50 mph aplica al salir.

| Gap `lim@ − stn` | Comportamiento |
| --- | --- |
| ≤ `LIMIT_AFTER_STATION_MAX_M` (50 m) | `next_sign_is_reduction_beyond_station` falso; `limit_sign_beyond_station` → **STATION** |
| > 50 m y ≤ 350 m (Four Oaks ~140 m) | `next_sign_is_reduction_beyond_station` → **LIMIT** (recorte 60→55 antes del andén) |
| Cartel delante del andén | Reglas cluster / proyección habituales |

Implementación: `limit_station_cluster.limit_sign_beyond_station`, `LIMIT_AFTER_STATION_MAX_M`.
Tests: `test_limit_sign_beyond_station_session_213010z`,
`test_pick_station_when_limit_sign_after_platform`.

### 10. Señal roja (paso 5)

Modos `station`, `signal` y `p1`: `signal_brake_enabled=True`. Plan gradual **además** de
emergencia (`p1_emergency`).

| Capa | Módulo | Regla |
| --- | --- | --- |
| Horizonte | `signal_apply_horizon_m` | **91 m** (~100 yd) en marcha ≤30 mph; **150 m** si spd &gt;30 mph (155148Z); lejos → WATCH |
| Terminal | `SignalBrakeConfig` | **`SIGNAL_TERMINAL_APPROACH_M` = 46 m (~50 yd)** — fase final antes del poste |
| Plan | `signal_plan.plan_brake_for_signal` | Perfil v→0 (reutiliza `plan_station_service_brake`, sin holgura horario) |
| Eval | `signal_brake.evaluate_signal_brake` | `target_from_stop_plan(..., max_apply_distance_m=HORIZON)` — WATCH lejos, APPLY dentro |
| Común | `service_brake` | `defer_apply` en `target_from_stop_plan`: fuera del horizonte nunca APPLY (evita parada @ 217 m) |
| Pick | `pick_p1_brake_target` | Rojo **gana** al cartel (incl. HOLD_DH diferido); vs andén ver geometría plataforma |
| Geometría plataforma | `signal_deferred_to_station_at_platform` | Rojo **detrás** del marker (`stn < sig`, `150617Z`) **o** pegado en cluster (&lt;350 m, `stn < 600 m`, `164240Z`) → **STATION** gana en pick |
| `signal_in_play` | Solo `signal_behind_station` | Rojo detrás del andén: no plan ni bloqueo creep RELEASE; **no** suprime cluster salida (arranque @ ~2 m sin plan STATION) |
| Salida andén | `should_suppress_signal_braking_for_departure` | Rojo @ ~2 m, tracción, spd ≤ 11 mph — esperar verde |
| Emergencia | `_attempt_p1_emergency` | SIGNAL **antes** que STATION; misma supresión salida que el plan |
| RELEASE creep | `should_block_creep_release_from_signal` | Solo **dentro** del horizonte (15–91 m) y spd &lt; 8 mph; lejos → acercar con cartel (`152037Z`) |
| RELEASE heredado | `decision._attempt_signal_inherited_release` | WATCH (`083405Z`) o rojo pasado/verde (`152037Z`): soltar B3 si muesca &gt; plan |
| RELEASE cartel | `limit_release_allowed` | Bloqueado con SIGNAL **`apply_now`** activo; usa `signal_in_play` (no rojo de salida tras andén) |
| Crawl | `plan_brake_for_signal` | `speed ≤ 0.5` y rojo **dentro** de 15–91 m → plan inmediato |
| Zona sin next | `evaluate_limit_brake` | `posted` vigente sin cartel siguiente (`lim=null` un tick) → HOLD_DH / contención zona |

Constantes señal (`signal_plan.py`):

| Constante | Valor | Notas |
| --- | --- | --- |
| `SIGNAL_BRAKE_HORIZON_M` | 91 m | ~100 yd — tope APPLY / parada total |
| `SIGNAL_TERMINAL_APPROACH_M` | 46 m | ~50 yd — terminal approach |
| `SIGNAL_RELEASE_BLOCK_MIN_DIST_M` | 15 m | Por debajo: creep hasta el poste |
| `SIGNAL_RELEASE_BLOCK_MAX_SPEED_MPH` | 8 | Umbral “crawl” para bloqueo RELEASE |
| `SIGNAL_WATCH_LIMIT_DEFER_M` | 150 m | WATCH señal no bloquea HOLD_DH más lejos |

Orden en `decision.py`: emergencia → cartel / andén / **señal** (pick) → **RELEASE señal heredado** → RELEASE cartel → idle / APPLY / COAST.

**Sesión `225433Z` (SPAD):** rojo @ 1040 m @ 56 mph → solo emergencia @ 61 m (tarde); HOLD_DH @15
ganaba a señal en recta final. Tras paso 5: `p1tgt=SIGNAL`, `COAST_PWR` lejos, B1+ en ventana.

**Sesión `083405Z`:** B3 heredado del cartel 45 + rojo WATCH @ 1 km → `command_none` y parada a
~750 m del poste. Tras unificación servicio: RELEASE a neutro si muesca > plan; plan señal activo
hasta ~0.5 mph.

**Sesión `143544Z` (zona 15 → señal roja):** overspeed hasta ~21.6 mph por `air_fill` con B1

~1.51 bar; RELEASE erróneo @70 m / 0.4 mph en crawl **dentro** del horizonte. Replay offline

(`V2/scripts/replay_jsonl.py`): en zona 15, `air_fill` 486→20 ticks y APPLY 124→679; sin

RELEASE creep con rojo activo dentro de ~100 yd.

**Sesión `152037Z` (primer semáforo, sin andén cercano):** parada total @ ~217 m (demasiado

lejos); tras el poste B3 no soltaba. Fix: horizonte **91 m** — lejos solo WATCH/cartel; APPLY

cerca del rojo; `signal_red` off → `_attempt_signal_inherited_release`.

**Sesión `164240Z` (zona 15 → andén Cross-City):** tras pasar cartel 15, `p1tgt=LIMIT` al next

50 @ ~283 m (cluster con andén @ ~287 m); overspeed en bajada −1 %%; al final `p1tgt=SIGNAL` con

rojo @ ~133 m pegado al marker. Fix: `_ignorable_limit_on_deferred_approach` + STATION WATCH;

`signal_deferred_to_station_at_platform` (pick STATION sobre rojo de salida en cluster). Cartel

15 real delante sigue mandando (`153551Z`). Replay: tick 2461 `STATION`; tick 2881 `STATION`.

**Orden objetivos Cross-City (andén final):** (1) semáforo entrada si APPLY/&lt;150 m → (2) zona

15 HOLD_DH → (3) **STATION** → (4) rojo salida en cluster = última prioridad en pick.

**Sesión `173809Z` (zona 15 overspeed en bajada):** tras cartel 15, hasta **21 mph** con

`eff=15` (−1 %%); `p1tgt=STATION` WATCH → `command_none` / `no_plan` sin HOLD_DH. Causas:

(1) pick STATION bloqueaba el mando aunque `evaluate_limit_brake` calculaba HOLD_DH;

(2) escalada B1→B2 inhibida en pendiente con overspeed claro. Fix: `_overlay_active_zone_hold`

en `decision.py`; `downhill_hold=True` en histéresis (`limit_notch`); horizonte next solo si

**recorte** (`15→50` no suprime HOLD_DH). Replay offline: **185** ticks `downhill_hold` en zona 15.

**Riesgo probe (sin fix Python):** `signal_red` puede desaparecer ~40 m con velocidad aún alta
(tick 20223) — latch Lua futuro.

#### FSM dwell andén (`p1_station_gate.py`)

Modo `station`: suprime **todo** P1 andén (plan + emergencia) en `STOPPED` / `DEPARTING`.

| Estado | Entrada | Salida |
| --- | --- | --- |
| `STOPPED` | `stn ≤ 55 m` y `spd ≤ 1.5` (spawn ~47 m) o puertas abiertas a baja velocidad | Puertas abrir→cerrar → `DEPARTING`; o `_left_platform` (ver abajo) |
| `DEPARTING` | Tras cerrar puertas | `spd ≥ 25 mph` o timeout 90 s → `None` |
| `None` | En marcha | Condiciones de parada → `STOPPED` |

**Salida sin ciclo puertas** (`_left_platform`): si el tren abandona el andén sin abrir puertas

(sesión `210853Z` — `fsm=STOPPED` toda la ruta y sin frenado de andén):

- `spd ≥ 25 mph`, o
- `stn > 55 m`, o
- `stn ≤ 1 m` con marcha (pasó el marker), o
- `stn = None` y `spd > 8 mph` (planning perdido en marcha).

**No** sale solo por velocidad dentro del andén (`12 mph` @ `stn=10 m` sigue `STOPPED`).

Capas de supresión (complementarias, no duplicadas):

1. **Gate** — apaga P1 estación en dwell (`loop.py` → `station_p1_enabled=False`).
2. **`should_suppress_station_braking_for_departure`** — anula plan con tracción en salida.
3. **`_station_emergency_suppressed`** — capa emergencia con tope ~15 mph.

#### Proyección al pasar el cartel (`station_may_ignore_limit_approach`)

Implementación: `cluster_approach_in_range` → cartel delante del andén →
`will_be_below_limit_at_pass` (velocidad ≤ posted+0.9 ahora y proyectada al pasar).

Sesión `20260909T231617Z`: con **52 mph** y cartel **55** @ 98 m el plan de cartel pedía APPLY pero
el tren ya iba legal; oscilaba `STATION↔LIMIT`.

Condiciones (cartel **delante** del andén):

1. `speed_mph ≤ posted_scoring_ceiling_mph(next)` (posted + 0.9 — techo TSW).
2. `projected_speed_mph_at_distance(speed, limit_dist_m)` ≤ mismo techo.

Proyección (`physics.projected_speed_mph_at_distance`):

- Si `accel_ms2 < −0.02` (frenando): usa aceleración del probe.
- Si no: coast (`COAST_DECEL_MS2` + pendiente).

Si ambas se cumplen → **no esperar** el cartel (`station_waits` falso), **no** tratar como overspeed
en cluster (`merged_approach_overspeed` falso), y `should_prefer_station_in_approach` devuelve
**STATION** aunque el plan de cartel tenga `apply_now=True` (WATCH o APPLY).

Entrada: `accel_ms2` del probe en `decision.evaluate_p1_tick` → `pick_p1_brake_target`.

Tests: `V2/tests/test_station_brake.py` (`test_will_be_below_limit_at_pass_coasting`,
`test_pick_station_when_below_limit_at_pass_despite_limit_apply`).

Constantes (`constants.py` / `p1_policy.py` / `physics.py`):

| Constante | Valor | Notas |
| --- | --- | --- |
| `HORIZON_SLACK_M` | 10 m | Sobre `bd(v→0)` para defer STATION |
| `STATION_APPROACH_PRIORITY_M` | 600 m | Horizonte preferencia andén (`constants.py`) |
| `STATION_APPROACH_MIN_SPEED_MPH` | 15 | No robar creep en andén |
| `TARGET_CLUSTER_GAP_M` | 350 m | Cluster cartel+andén |
| `LIMIT_AFTER_STATION_MAX_M` | 50 m | Cartel pegado tras marker → andén primero |
| `PLATFORM_AT_STOP_M` | 55 m | Gate FSM: radio parada en andén |
| `DEPARTING_CLEAR_MPH` | 25 | Gate: marcha clara / fin `DEPARTING` |

**No aplica** feedback decel en STATION (solo cartel en `limits.py`). Emergencia andén:
`p1_emergency`
independiente de esta prioridad.

---

## Qué descartamos de v1 (comportamiento malo o confuso)

| Legacy | Por qué no en V2 |
| --- | --- |
| Tres contenciones solapadas (posted + contain + approach) | Una sola **HOLD_DH** + un **BRAKE_LIMIT** |
| Posted hold sin tope de distancia al next cartel | H1: solo **fuera** del horizonte del next |
| `apply_now=True` B1 continuo lejos del cartel | HOLD_DH: coast / B1 **si repunte** |
| Prioridad posted vs next opaca | Regla explícita: **next gana dentro del horizonte** |
| `SAFETY_MARGIN` 1.40 | V2 tuning **1.10** (validar JSONL; sesión 20260906) |
| Comparar con v1 en mantenimiento | Criterio = tests V2 + sesión aceptada |

---

## Modelo V2 (desde cero)

### Entradas (probe)

| Campo | Uso |
| --- | --- |
| `speed_ms` | Velocidad actual |
| `speed_limit_ms` | Límite **vigente** (zona actual) |
| `next_limit_ms` + `dist_limit_cm` | Cartel **siguiente** |
| `gradient_pct` | Bajada / subida |
| `brake_cyl_bar` | L4 (opcional) |
| `lever_notch` | RELEASE / COAST_PWR |
| `signal_red` + `signal_dist_cm` | Semáforo rojo adelante (C1 probe; plan gradual + emergencia) |

### Salida

`LimitPlan` (hoy `BrakeTargetResult` + `LimitBrakeDecision`):

- `mode` — uno de la tabla arriba
- `target_mph`, `handle`, `dist_start`, `apply_now`
- `reason` — trace (`plan`, `downhill_hold`, `release`, …)

### Flujo objetivo (un solo planificador)

```text
```

**Eliminar** en el rediseño final: rutas legacy `try_downhill_approach_hold` separadas del latch. La
contención de zona (`try_current_zone_downhill_contain`) + **HOLD_DH** (`try_posted_downhill_hold`)
comparten `_build_downhill_hold_result`; el efecto bueno se absorbe en **HOLD_DH** +
**BRAKE_LIMIT**.

### H1 (implementado — primer bloque del diseño nuevo)

| Fase | Condición | Modo | Objetivo |
| --- | --- | --- | --- |
| 1a | `dist_next > horizon`, bajada, `spd > posted + 0.5`, next baja (60→55) | **zone_contain** | **60.5** → coast **59.5** |
| 1b | `dist_next > horizon`, bajada, `spd > posted + 0.5`, misma zona (60→60) | **HOLD_DH** | **60.5** |
| 2 | `dist_next ≤ horizon` | **BRAKE_LIMIT** al next | **posted_next − 1** (55→54) |

Código actual: `limit_containment.py`, `limits.py`, `decision.py` · tests:
`V2/tests/test_h1_downhill.py`.

---

## Constantes V2 (tuning — no sagradas)

Todas en `constants.py` o sección `P1_LIMIT_TUNING` (pendiente agrupar).

| Constante | Valor V2 | Notas |
| --- | --- | --- |
| `SAFETY_MARGIN` | 1.10 | Validar JSONL (era 1.20) |
| `LIMIT_ZONE_HOLD_OVER_MPH` | 0.5 | Techo HOLD bajada suave (60→60.5) |
| `LIMIT_ZONE_HOLD_OVER_STEEP_MPH` | 0.2 | Techo HOLD bajada fuerte −1 %% (60→60.2) |
| `zone_hold_over_mph(grad)` | 0.5→0.2 | Interpola según pendiente |
| `LIMIT_ZONE_COAST_OVER_OPS_MPH` | 0.5 | Suelo coast tras contener (59→59.5) |
| `LIMIT_SCORING_MAX_OVER_MPH` | 0.9 | Penalización TSW (histéresis) |
| `DOWNHILL_LIMIT_GRADIENT_PCT` | −0.3 | Umbral bajada |
| `PASSENGER_OPS_MARGIN_MPH` | 1.0 | Solo **BRAKE_LIMIT** al next (55→54); no HOLD_DH |
| `LIMIT_DOWNHILL_COAST_TRIM_MPH` | 2.0 | Coast/defer cerca del ops del next; tope escalada B2/B3 en bajada |
| `LIMIT_CONTAIN_ESCALATE_OVER_MPH` | 0.65 | Subir muesca en HOLD si `spd > techo + 0.65` |
| `LIMIT_RELEASE_MAX_OVER_MPH` | 0.4 | RELEASE en llano |
| `limit_release_over_mph(grad)` | 0.4→0.55 | Bajada: banda más ancha si más pendiente (−1 %% → ~0.55) |
| Trigger repunte bajada | 0.20 / 0.28 / 0.35 mph | **Pendiente** — no cableado aún |
| `LIMIT_REACTION_S` | 1.5 | + `brake_fill_s` |
| `LIMIT_COAST_BAND_MPH` | 0.25 | Revisar |
| `DECEL_SHORTFALL_RATIO` | 0.70 | Feedback: escalar si `a_obs < ratio × a_pred` |
| `WEAK_DECEL_TICKS` | 2 | Ticks consecutivos con shortfall antes de subir muesca |
| `DECEL_MIN_PRED_MS2` | 0.15 | Ignorar perfil por debajo (ruido) |
| `DECEL_MIN_OBS_MS2` | 0.08 | Ignorar accel probe por debajo (ruido) |
| `BRAKE_PLAN_LARGE_DROP_MPH` | 18.0 | **Doble uso:** (1) `pick_weakest`: caída **velocidad** al objetivo → mínimo B2; (2) `downhill_defer_brake_commit` subida: caída **posted** zona ≥18 → no coast-trim vs ops del next si legal en zona vigente |
| `PRESSURE_BRAKING_MIN_BAR` | 1.55 | Gate aire B1 Class 323 (`physics` / `brake_air`) |

Cambiar solo con test + sesión documentada.

---

## Roadmap código (de inventario legacy → V2 nativo)

| Paso | Qué | Estado |
| --- | --- | --- |
| **0** | Este documento + política “ideas sí, port no” | ✅ |
| **1** | H1 HOLD_DH + horizonte; contención 60→55 lejos @ **60.5**; RELEASE ~**59.5**; BRAKE_LIMIT @ **54** en horizonte | ✅ |
| **2** | Fusionar legacy contain/approach en HOLD_DH + BRAKE_LIMIT | ✅ |
| **3** | Un módulo `limit_planner.py` (modos explícitos); `limits.py` = fachada fina | ⬜ |
| **4** | RELEASE/coast reescritos con mismos modos (sin duplicar bajada) | ⬜ |
| **5** | Probe `brake_cyl_bar` + L4 en el mismo planificador | ⬜ |
| **6** | Shims v1 → `V2/tsw6v2/` (`physics`, `plan`, `command`, `limit_brake`); tests root cartel alineados | ✅ |

### Criterio de hecho (V2 only)

```bat
```

Validación multi-sesión: [VALIDACION_P1_SESIONES.md](VALIDACION_P1_SESIONES.md).

- JSONL: modos esperados (HOLD_DH lejos, BRAKE_LIMIT cerca, sin “Contención bajada” legacy salvo

  decisión explícita).

- **No** comparar con `tests/test_brake_v2.py` legacy.

---

## Evidencia que motivó el rediseño

Sesión `logs/v2/20260904T154957Z_cross-city_limit.jsonl` (pre-H1):

- 72 % APPLY = contención legacy mezclada con BRAKE.
- Freno a 60 mph con cartel 55 @ 700 m — no era latch, era posted hold mal acotado.

Tras H1, repetir sesión y comparar capas `HOLD_DH` vs `BRAKE`.

---

## Apéndice A — Inventario legacy (solo referencia histórica)

Detalle regla a regla del port antiguo: `archive/braking_v1_autopilot/`. **No usar para implementar
V2.**

IDs A–G del inventario 2026-09-04: sustituidos por modos **NONE / WATCH / HOLD_DH / BRAKE_LIMIT /
RELEASE / COAST_PWR**.

---

## Apéndice B — Mapa código cartel (paso 3)

| Módulo | Rol |
| --- | --- |
| `constants.py` | Umbrales cartel (plan / HOLD_DH / RELEASE) |
| `planning.py` | GetData, `is_ascending_limit_exit`, `resolve_limit_objective` |
| `limit_horizon.py` | Horizonte cinemático BRAKE_LIMIT (`next_limit_brake_horizon_m`) |
| `limit_containment.py` | HOLD_DH + zone_contain (usa `limit_horizon`) |
| `limit_state.py` | Latch BRAKE_LIMIT; `snapshot()` / `replace_from()` |
| `limit_notch.py` | Muesca + histéresis + defer (`next_brake_overrides_zone_hold`) |
| `brake_feedback.py` | Bucle corto `a_obs` vs `a_pred` → escalada B1→B2 |
| `limits.py` | Fachada `evaluate_limit_brake` |
| `target.py` | `BrakeTargetResult` |
| `command.py` | RELEASE cinemático + COAST / APPLY |
| `decision.py` | Tick + L4 aire + RELEASE con `accel_ms2` / perfil |
| `autopilot_limit.py` | Puente autopilot GUI → `evaluate_limit_tick` |
| `physics.py` | APPLY `s = v²/2a` + RELEASE `v + a·fill` + proyección `projected_speed_mph_at_distance` |

## Apéndice C — Mapa código andén + prioridad (paso 3)

| Módulo | Rol |
| --- | --- |
| `station_plan.py` | Perfil v→0 (B1/B2/B3); ETA desactivada por defecto |
| `station_brake.py` | `evaluate_station_brake` → `BrakeTargetResult` STATION |
| `limit_station_cluster.py` | Cluster 350 m, `limit_sign_beyond_station`, `exit_signal_clustered_with_platform_stop` |
| `signal_plan.py` | `plan_brake_for_signal`, `signal_deferred_to_station_at_platform`, horizontes APPLY |
| `signal_brake.py` | `evaluate_signal_brake` → `BrakeTargetResult` SIGNAL |
| `service_brake.py` | `target_from_stop_plan` (andén + señal) |
| `p1_policy.py` | `pick_p1_brake_target`, `_resolve_deferred_station_pick`, `should_allow_station_watch_when_deferred` |
| `p1_station_gate.py` | FSM `STOPPED`/`DEPARTING`; suprime P1 andén en dwell |
| `planning_poller.py` / `planning_feed.py` | HTTP `DriverAid.TrackData` + anti-salto distancia |
| `p1_emergency.py` | B3 si distancia crítica al andén / señal |
| `session_report.py` | Replay HTML/JSONL; puertas, marcadores APPLY, zoom, señal rojo |
| `trace.py` | JSONL tick + investigate (`sig=ROJO@…m`) |
| `decision.py` | `evaluate_p1_tick`: emergencia → pick → RELEASE → `_overlay_active_zone_hold` → L4 |

---

## Relacionados

- [PLAN_V2 §2 Física](PLAN_V2.md#2-física-qué-investigar-e-introducir)
- [p1_limit_capas.html](p1_limit_capas.html) — diagramas cartel, pick cartel↔andén, cluster, FSM

  gate

- [MANTENIMIENTO § Plan cartel](MANTENIMIENTO.md#plan-cartel-p1-limit_)
- [VALIDACION_P1_SESIONES.md](VALIDACION_P1_SESIONES.md) — protocolo campo Cross-City

#### Changelog

| Fecha | Qué |
| --- | --- |
| 2026-09-13 | Sesión `173809Z`: STATION WATCH no bloquea HOLD_DH (`_overlay_active_zone_hold`); escalada B2 en overspeed zona 15 (`downhill_hold` en histéresis); `15→50` no cede horizonte HOLD_DH |
| 2026-09-13 | Sesión `164240Z`: zona 15 + cartel 50 ignorable → STATION WATCH (`_ignorable_limit_on_deferred_approach`); rojo salida en cluster → STATION gana pick (`signal_deferred_to_station_at_platform`); refactor ramas deferred |
| 2026-09-13 | Sesión `155148Z`: rojo &lt;150 m gana cartel APPLY; horizonte APPLY 150 m si spd &gt;30 mph (`signal_apply_horizon_m`) |
| 2026-09-13 | Sesión `153551Z`: andén diferido + cartel 15 WATCH @ &lt;600 m → `pick` LIMIT (no `None` ni señal WATCH lejana) |
| 2026-09-13 | Sesión `152037Z`: horizonte señal **91 m** (~100 yd); `defer_apply` en `service_brake`; RELEASE tras rojo pasado; creep bloqueado solo 15–91 m; `_attempt_signal_inherited_release` |
| 2026-09-13 | Señal tras andén: `signal_behind_station` si `stn &lt; sig` — no frenar ~200 m antes del rojo de salida (`150617Z`) |
| 2026-09-13 | Sesión `143544Z`: `air_ready` vía `brake_decel_sample_ready`; RELEASE bloqueado con `signal_dist_m` en creep **dentro** del horizonte; HOLD_DH con `posted` sin `next`; `resolve_signal_dist_m`; replay `scripts/replay_jsonl.py` |
| 2026-09-13 | Señal roja: APPLY solo dentro de ~100 yd; WATCH lejos no bloquea HOLD_DH (`102222Z`) |
| 2026-09-13 | Fix `zone_hold_over_mph`: cap @ −1 %% (no margen negativo en −1.74 %%); techo HOLD 15→15.2 y latch rearm ~15.75 (`095417Z`) |
| 2026-09-13 | RELEASE huérfano: freno HOLD_DH/B2 sin plan (`no_plan`) bajo techo zona — sesión `095417Z` (B2 tras 15→30, objetivo 50 lejos) |
| 2026-09-13 | Latch coast zona bajada: tras RELEASE `eff_floor`, inhibir HOLD_DH hasta `spd > techo_zona + limit_release_over` (evita bombeo HOLD↔RELEASE @ ~15 mph, sesión `092947Z`) |
| 2026-09-13 | Servicio unificado (`service_brake`): señal/andén RELEASE si freno heredado > plan WATCH; señal activa bajo 1 mph lejos del poste; `_limit_release_allowed` solo con señal `apply_now` (`083405Z`) |
| 2026-09-13 | RELEASE `eff_floor` en subida de cartel: lejos del next (`081745Z` 15→50) y en horizonte (`142034Z` 10→30); `ascending_exit` no bloquea suelo zona vigente |
| 2026-09-13 | Paso 5 señal: `evaluate_signal_brake`, `signal_plan`, `service_brake`; rojo gana HOLD_DH; emergencia SIGNAL con supresión salida; sesión ref. `225433Z` |
| 2026-09-13 | Modo station: RELEASE antes de `no_plan` (`224046Z` HOLD_DH zona 15); `pick` sin WATCH con andén diferido + sin `p1tgt` fantasma (`221258Z`); coast-trim subida no en caída posted grande 60→35 |
| 2026-09-12 | Evaluación dual con snapshots; `limit_horizon.py`; coast trim subida (`coast_trim_deferred`); sin HOLD_DH en salida lenta→rápida en cuesta; caída grande → B2; aire 323 @ 1.55 bar; trace/replay señal |
| 2026-09-10 | `p1_limit_capas.html`: ramas andén, pick, geometría cluster, FSM gate |
| 2026-09-10 | Cartel tras andén (`213010Z`): `limit_sign_beyond_station`, `LIMIT_AFTER_STATION_MAX_M` |
| 2026-09-10 | FSM dwell `p1_station_gate` + salida `_left_platform` (`210853Z`); RELEASE llano sin cinemática |
| 2026-09-10 | `HORIZON_SLACK_M` 15→10 m; reacción terminal andén ligeramente más temprana |
| 2026-09-10 | §9 prioridad cartel↔andén; `will_be_below_limit_at_pass` + proyección al pasar cartel |
| 2026-09-10 | RELEASE cinemático BRAKE_LIMIT (`v + a_net·fill`); doc validación actualizada |
| 2026-09-09 | Doc validación multi-sesión; depurado `should_coast_throttle_before_brake` |
| 2026-09-09 | Feedback/EMA gated por `brake_decel_sample_ready` (palanca + presión cilindro) |
| 2026-09-08 | EMA online en sesión P1 (`observe_brake_decel` → perfil al cerrar) |
| 2026-09-08 | Feedback decel cerrado (`brake_feedback.py`); JSONL `fb`; un escalón/tick vía reset en `_step_stronger` |
| 2026-09-08 | Prioridad `limits.py`: WATCH no bloquea HOLD_DH; override solo en defer; RELEASE `eff_floor` gated por horizonte |
| 2026-09-06 | HOLD techo escala con pendiente: `zone_hold_over_mph` 0.5→0.2 @ −1 %% |
| 2026-09-06 | Archive v1; `planning.py` + `constants.py` umbrales; doc alineado |
| 2026-09-04 | Inventario legacy + sesión Cross-City |
| 2026-09-04 | H1 implementado (`HOLD_DH`, `downhill_hold`) |
| 2026-09-04 | H1b (obsoleto): techo posted−1 en HOLD — sustituido por posted+0.9 en zona vigente |
