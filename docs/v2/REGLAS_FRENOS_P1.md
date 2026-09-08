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
- **`a`** de learner si hay perfil (`logs/profiles/<vehicle>.json`, auto-carga en sesión); si no, fracciones B1/B2/B3 UK.
- Pendiente: **una vez** — en `a` aprendida **o** en `g` en la fórmula, nunca las dos.
- TSW penaliza **> límite + 1 mph** → en plan usamos **+0,9 mph** sobre el cartel **vigente** (techo de scoring).
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

1. **BRAKE_LIMIT** con `apply_now` → gana (dentro del horizonte del next).
2. **Contención bajada** (`pick_downhill_containment`) si superas el techo de la zona vigente.
3. **BRAKE_LIMIT** en WATCH (lejos, bajo techo de zona).

**Caso 60→55 en bajada** (tests: `test_h1_downhill.py`):

| Velocidad | Dist. al cartel 55 | Modo | Objetivo |
| --- | --- | --- | --- |
| ≤ 60.5 | Lejos (> horizonte) | WATCH | — |
| > 60.5 | Lejos | HOLD_DH / zone_contain | **60.5**, B1 suave; RELEASE ~**59.5** |
| Cualquiera | ≤ horizonte | BRAKE_LIMIT | **54**, B1 primero; escalar solo cerca de 54+2 mph |

Excepciones:

- **60→55**: contención @ **60.5** fuera del horizonte; soltar en **59.5** si hay presión/coast eficiente.
- **55→45** (y cualquier bajada): RELEASE al cartel next en **ops+0.5** (45→**44.5**); no arrastrar B1 hasta ~40.
- **60→60** (misma zona): HOLD_DH si `spd > 60.5`.
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
limit_plan_tick(snapshot, state)
│
├─ ¿Freno puesto? → RELEASE (reglas bajada)
│
├─ horizon_next = f(spd, next_limit, grad, fill)
│
├─ SI bajada Y dist_next > horizon_next Y spd > posted_zone_hold_ceiling (posted + 0.5)
│     → HOLD_DH / zone_contain  (Fase 1 — H1 ✅)
│
├─ SI spd > next_limit + banda Y dist_next ≤ horizon_next
│     → BRAKE_LIMIT (latch + muesca mínima + histéresis + L4)
│
├─ SI plan listo pero fuera ventana
│     → WATCH / WAIT
│
└─ command_layer: COAST_PWR si power → APPLY / RELEASE → IPC
```

**Eliminar** en el rediseño final: rutas legacy `try_downhill_approach_hold` separadas del latch. La contención de zona (`try_current_zone_downhill_contain`) + **HOLD_DH** (`try_posted_downhill_hold`) comparten `_build_downhill_hold_result`; el efecto bueno se absorbe en **HOLD_DH** + **BRAKE_LIMIT**.

### H1 (implementado — primer bloque del diseño nuevo)

| Fase | Condición | Modo | Objetivo |
| --- | --- | --- | --- |
| 1a | `dist_next > horizon`, bajada, `spd > posted + 0.5`, next baja (60→55) | **zone_contain** | **60.5** → coast **59.5** |
| 1b | `dist_next > horizon`, bajada, `spd > posted + 0.5`, misma zona (60→60) | **HOLD_DH** | **60.5** |
| 2 | `dist_next ≤ horizon` | **BRAKE_LIMIT** al next | **posted_next − 1** (55→54) |

Código actual: `limit_containment.py`, `limits.py`, `decision.py` · tests: `V2/tests/test_h1_downhill.py`.

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
python -m pytest V2/tests/ -q
V2\run_p1_session.bat limit cross-city
python scripts\tools\summarize_v2_limit.py logs\v2\ULTIMA.jsonl
```

- JSONL: modos esperados (HOLD_DH lejos, BRAKE_LIMIT cerca, sin “Contención bajada” legacy salvo decisión explícita).
- **No** comparar con `tests/test_brake_v2.py` legacy.

---

## Evidencia que motivó el rediseño

Sesión `logs/v2/20260904T154957Z_cross-city_limit.jsonl` (pre-H1):

- 72 % APPLY = contención legacy mezclada con BRAKE.
- Freno a 60 mph con cartel 55 @ 700 m — no era latch, era posted hold mal acotado.

Tras H1, repetir sesión y comparar capas `HOLD_DH` vs `BRAKE`.

---

## Apéndice A — Inventario legacy (solo referencia histórica)

Detalle regla a regla del port antiguo: `archive/braking_v1_autopilot/`. **No usar para implementar V2.**

IDs A–G del inventario 2026-09-04: sustituidos por modos **NONE / WATCH / HOLD_DH / BRAKE_LIMIT / RELEASE / COAST_PWR**.

---

## Apéndice B — Mapa código cartel (paso 3)

| Módulo | Rol |
| --- | --- |
| `constants.py` | Umbrales cartel (plan / HOLD_DH / RELEASE) |
| `planning.py` | GetData, `is_ascending_limit_exit`, `resolve_limit_objective` |
| `limit_containment.py` | HOLD_DH + zone_contain + `next_limit_brake_horizon_m` |
| `limit_state.py` | Latch BRAKE_LIMIT |
| `limit_notch.py` | Muesca + histéresis |
| `limits.py` | Fachada `evaluate_limit_brake` |
| `target.py` | `BrakeTargetResult` |
| `command.py` | RELEASE / COAST / APPLY |
| `decision.py` | Tick + L4 aire |
| `autopilot_limit.py` | Puente autopilot GUI → `evaluate_limit_tick` |
| `physics.py` | `s = v²/2a` |

---

## Relacionados

- [PLAN_V2 §2 Física](PLAN_V2.md#2-física-qué-investigar-e-introducir)
- [p1_limit_capas.html](p1_limit_capas.html)
- [MANTENIMIENTO § Plan cartel](MANTENIMIENTO.md#plan-cartel-p1-limit_)

**Changelog**

| Fecha | Qué |
| --- | --- |
| 2026-09-06 | HOLD techo escala con pendiente: `zone_hold_over_mph` 0.5→0.2 @ −1 %% |
| 2026-09-06 | Archive v1; `planning.py` + `constants.py` umbrales; doc alineado |
| 2026-09-04 | Inventario legacy + sesión Cross-City |
| 2026-09-04 | H1 implementado (`HOLD_DH`, `downhill_hold`) |
| 2026-09-04 | H1b (obsoleto): techo posted−1 en HOLD — sustituido por posted+0.9 en zona vigente |
