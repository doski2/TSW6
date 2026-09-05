# Reglas de frenos P1 — diseño V2 desde cero

**Estado:** diseño acordado (2026-09-04) · **H1** implementado (primer paso)  
**Plan:** [PLAN_V2.md](PLAN_V2.md) · **Código:** [CODIGO_V2.md](CODIGO_V2.md)

---

## Política (no negociable)

| Sí | No |
| --- | --- |
| Diseñar reglas en `V2/tsw6v2/` con tests + JSONL | Copiar o “igualar” `tsw6/braking/v2/limit_brake.py` |
| Tomar de v1 solo **ideas** validadas (física, capas, UK 323) | Heredar capas paralelas legacy (contención ×3, prioridades opacas) |
| Cada regla: motivo + capa trace + test | Paridad ciega con v1 “porque antes estaba” |
| Perfeccionar con sesiones Cross-City | Ampliar `tsw6/autopilot/` ni `tsw6/braking/` |

**v1** (`limit_brake.py`, coordinator) = **archivo muerto** para producto nuevo. Solo laboratorio histórico.

---

## Qué conservamos de v1 (solo ideas)

Ideas que **sí** entran en el diseño V2 — reimplementadas, no pegadas.

### 1. Física única

- Una distancia: **`s = (v² − u²) / (2a_eff)`** (+ margen reacción + fill aire).
- **`a`** de learner si hay perfil; si no, fracciones B1/B2/B3 UK.
- Pendiente: **una vez** — en `a` aprendida **o** en `g` en la fórmula, nunca las dos.
- TSW penaliza **> límite + 1 mph** → techo operativo **+0,9 mph** en plan.

### 2. Objetivos claros por tick

Cada tick el planificador elige **un modo** (no una pila de `if` legacy):

| Modo | Intención |
| --- | --- |
| **NONE** | Sin cartel / sin plan |
| **WATCH** | Cartel lejos; calcular pero no mandar |
| **HOLD_DH** | Bajada: sujetar **límite vigente** hasta horizonte del **siguiente** cartel |
| **BRAKE_LIMIT** | Frenar al **siguiente** cartel (latch + muesca mínima) |
| **RELEASE** | En banda; soltar (con excepciones bajada) |
| **COAST_PWR** | Quitar tracción antes de freno |

### 3. Muescas UK pasajeros

- Servicio B1→B3 (handle 3→1); **un escalón por tick** (IPC + aire).
- Elegir la **más débil que basta**; subir si tarde o corto de distancia.
- Emergencia (notch 0) solo pegado al objetivo.

### 4. Aire (L4 lite)

- No APPLY sin presión; no bombar tras soltar; escalón acorde a `brake_cyl_bar`.
- Depende de probe — sin presión, modo degradado documentado.

### 5. Trazabilidad

- Cada decisión → `p1.reason` + capa (`p1_layers`) + JSONL para debatir tuning.

---

## Qué descartamos de v1 (comportamiento malo o confuso)

| Legacy | Por qué no en V2 |
| --- | --- |
| Tres contenciones solapadas (posted + contain + approach) | Una sola **HOLD_DH** + un **BRAKE_LIMIT** |
| Posted hold sin tope de distancia al next cartel | H1: solo **fuera** del horizonte del next |
| `apply_now=True` B1 continuo lejos del cartel | HOLD_DH: coast / B1 **si repunte** |
| Prioridad posted vs next opaca | Regla explícita: **next gana dentro del horizonte** |
| `SAFETY_MARGIN` 1.40 | V2 tuning **1.20** (validar JSONL) |
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
├─ SI bajada Y dist_next > horizon_next Y spd > posted + trigger
│     → HOLD_DH  (Fase 1 — H1 ✅)
│
├─ SI spd > next_limit + banda Y dist_next ≤ horizon_next
│     → BRAKE_LIMIT (latch + muesca mínima + histéresis + L4)
│
├─ SI plan listo pero fuera ventana
│     → WATCH / WAIT
│
└─ command_layer: COAST_PWR si power → APPLY / RELEASE → IPC
```

**Eliminar** en el rediseño final: `try_downhill_containment` y `try_downhill_approach_hold` como rutas separadas del latch — su efecto bueno se absorbe en **HOLD_DH** + **RELEASE bajada**.

### H1 (implementado — primer bloque del diseño nuevo)

| Fase | Condición | Modo |
| --- | --- | --- |
| 1 | `dist_next > horizon`, bajada, sobre posted | **HOLD_DH** (+ **COAST_PWR** si power) |
| 2 | `dist_next ≤ horizon` | **BRAKE_LIMIT** al next |

Código actual: `limit_containment.py`, `limits.py`, `decision.py` · tests: `V2/tests/test_h1_downhill.py`.

---

## Constantes V2 (tuning — no sagradas)

Todas en `constants.py` o sección `P1_LIMIT_TUNING` (pendiente agrupar).

| Constante | Valor V2 | Notas |
| --- | --- | --- |
| `SAFETY_MARGIN` | 1.20 | Validar JSONL |
| `LIMIT_SCORING_MAX_OVER_MPH` | 0.9 | Penalización TSW |
| `DOWNHILL_LIMIT_GRADIENT_PCT` | −0.3 | Umbral bajada |
| `PASSENGER_OPS_MARGIN_MPH` | 1.0 | HOLD_DH y **BRAKE_LIMIT** (60→59, 55→54) |
| Trigger repunte bajada | 0.20 / 0.28 / 0.35 mph | Según pendiente |
| `LIMIT_REACTION_S` | 1.5 | + `brake_fill_s` |
| `LIMIT_COAST_BAND_MPH` | 0.25 | Revisar |

Cambiar solo con test + sesión documentada.

---

## Roadmap código (de inventario legacy → V2 nativo)

| Paso | Qué | Estado |
| --- | --- | --- |
| **0** | Este documento + política “ideas sí, port no” | ✅ |
| **1** | H1 HOLD_DH + horizonte; sin HOLD en bajada 60→55; techo **59** (posted−1) | ✅ |
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

Detalle regla a regla del port antiguo (`limit_brake.py` + `command.py`): ver commit anterior o `tsw6/braking/v2/limit_brake.py`. **No usar para implementar V2.**

IDs A–G del inventario 2026-09-04: sustituidos por modos **NONE / WATCH / HOLD_DH / BRAKE_LIMIT / RELEASE / COAST_PWR**.

---

## Apéndice B — Mapa código actual (transitorio)

Hasta el paso 3 del roadmap, la lógica sigue repartida:

| Módulo | Rol transitorio |
| --- | --- |
| `limit_containment.py` | HOLD_DH + `next_limit_brake_horizon_m` |
| `limit_state.py` | Latch BRAKE_LIMIT |
| `limit_notch.py` | Muesca + histéresis |
| `limits.py` | Orquestación (a simplificar) |
| `command.py` | RELEASE / COAST |
| `decision.py` | Tick + L4 |
| `physics.py` | `s = v²/2a` |

---

## Relacionados

- [PLAN_V2 §2 Física](PLAN_V2.md#2-física-qué-investigar-e-introducir)
- [p1_limit_capas.html](p1_limit_capas.html)
- [MANTENIMIENTO § Plan cartel](MANTENIMIENTO.md#plan-cartel-p1-limit_)

**Changelog**

| Fecha | Qué |
| --- | --- |
| 2026-09-04 | Inventario legacy + sesión Cross-City |
| 2026-09-04 | H1 implementado (`HOLD_DH`, `downhill_hold`) |
| 2026-09-04 | **H1b** — sin HOLD_DH en 60→55; techo pasajeros posted−1 mph (59) |
