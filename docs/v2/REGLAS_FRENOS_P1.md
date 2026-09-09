# Reglas de frenos P1 — diseño V2 desde cero

**Estado:** diseño acordado (2026-09-04) · **H1** implementado (primer paso)
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

- **55→45** (y cualquier bajada): RELEASE al cartel next en **ops+0.5** (45→**44.5**); no arrastrar

  B1 hasta ~40; no soltar por `eff_floor` de zona vigente **dentro** del horizonte.

- **60→60** (misma zona): HOLD_DH si `spd >` techo zona.
- **35→60** (subida de límite): sin contención — dejar acelerar (`is_ascending_limit_exit`).

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

### 4. Muescas UK pasajeros

- Servicio B1→B3 (handle 3→1); **un escalón por tick** (IPC + aire).
- Elegir la **más débil que basta**; subir si tarde o corto de distancia.
- Emergencia (notch 0) solo pegado al objetivo.

### 5. Aire (L4 lite)

- No APPLY sin presión; no bombar tras soltar; escalón acorde a `brake_cyl_bar`.
- Depende de probe — sin presión, modo degradado documentado.

### 6. Trazabilidad

- Cada decisión → `p1.reason` + capa (`p1_layers`) + JSONL para debatir tuning.

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
| **BRAKE_LIMIT** (latch al 54) | Antes de 54 mph si el fill seguiría frenando | `v_proy = v + a_net·brake_fill_s ≤ target + banda` |

- `a_net`: `accel_ms2` del probe si hay frenado; si no, `predict_decel` del learner (**ya incluye

  pendiente** — no volver a sumar `g`).

- `brake_fill_s`: del perfil / `BrakeAirTracker`.
- En bajada cerca del cartel, `should_hold_limit_brake_downhill` no bloquea el latch final (`spd ≤

  latch + 2 mph`).

Módulos: `physics.projected_speed_mph_after_brake_fill`, `command.resolve_release_command`. Tests:
`test_release.py` (kinematic).

**No planificado (2026-09-10):** aprendizaje por distancia de parada integrada u observación en
HOLD_DH — seguir EMA tick a tick hasta estabilizar perfil en campo.

### 9. Prioridad cartel ↔ andén (dos objetivos)

Modo `station`: cada tick hay hasta **dos planes** (`evaluate_limit_brake` + `evaluate_station_brake`);
`pick_p1_brake_target` (`p1_policy.py`) elige **uno** para P1. Cluster: cartel **antes** del andén
con gap ≤ `TARGET_CLUSTER_GAP_M` (350 m).

```text
limit_target + station_target
  → station_waits_for_approach_limit?     → LIMIT (Four Oaks: recorte más allá del andén)
  → merged_approach_overspeed?            → LIMIT (cluster y spd > next + 0.5)
  → parada unificada y spd > next + 0.4?  → LIMIT (salvo proyección OK — abajo)
  → should_prefer_station_in_approach?    → STATION
  → should_defer_station_brake?           → LIMIT si APPLY; si no, None (sin objetivo fantasma)
  → urgencia (dist_start menor gana)
```

| Regla | Cuándo | Objetivo |
| --- | --- | --- |
| `should_defer_station_brake` | Andén más lejos que `bd(v→0)` servicio + 15 m | Sin STATION todavía |
| `station_waits_for_approach_limit` | Recorte HUD invertido o overspeed al cartel en cluster | LIMIT primero |
| `merged_approach_overspeed` | Cluster, cartel > 50 m, spd > next + 0.5 | LIMIT |
| `should_prefer_station_in_approach` | Andén < 600 m, spd > 15 mph, cartel no exige freno | **STATION** |
| `station_may_ignore_limit_approach` | Cartel delante en cluster + proyección legal | **STATION** anticipado |

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

Constantes (`p1_policy.py` / `physics.py`):

| Constante | Valor | Notas |
| --- | --- | --- |
| `HORIZON_SLACK_M` | 15 m | Sobre `bd(v→0)` para defer STATION |
| `STATION_APPROACH_PRIORITY_M` | 600 m | Horizonte preferencia andén |
| `STATION_APPROACH_MIN_SPEED_MPH` | 15 | No robar creep en andén |
| `TARGET_CLUSTER_GAP_M` | 350 m | Cluster cartel+andén |

**No aplica** feedback decel en STATION (solo cartel en `limits.py`). Emergencia andén: `p1_emergency`
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
| `limit_containment.py` | HOLD_DH + zone_contain + `next_limit_brake_horizon_m` |
| `limit_state.py` | Latch BRAKE_LIMIT |
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
| `limit_station_cluster.py` | Cluster 350 m, `will_be_below_limit_at_pass`, `station_waits` |
| `p1_policy.py` | `pick_p1_brake_target`, defer horizonte, preferencia andén |
| `planning_poller.py` / `planning_feed.py` | HTTP `DriverAid.TrackData` + anti-salto distancia |
| `p1_emergency.py` | B3 si distancia crítica al andén / señal |
| `decision.py` | `evaluate_p1_tick`: emergencia → release → pick objetivo → L4 |

---

## Relacionados

- [PLAN_V2 §2 Física](PLAN_V2.md#2-física-qué-investigar-e-introducir)
- [p1_limit_capas.html](p1_limit_capas.html)
- [MANTENIMIENTO § Plan cartel](MANTENIMIENTO.md#plan-cartel-p1-limit_)
- [VALIDACION_P1_SESIONES.md](VALIDACION_P1_SESIONES.md) — protocolo campo Cross-City

#### Changelog

| Fecha | Qué |
| --- | --- |
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
