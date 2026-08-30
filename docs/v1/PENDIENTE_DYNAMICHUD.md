# Pendiente — Probe UE4SS (referencia operativa)

**No es el backlog del proyecto.** Tareas y orden → [v2/PLAN_V2.md § Orden](../v2/PLAN_V2.md#orden-de-implementación).

**Objetivo:** documentar el **probe** Class 323: reglas Lua, IPC, señales de log, bitácora de sesiones.

**Plan maestro:** [v2/PLAN_V2.md](../v2/PLAN_V2.md).

**Estado runtime (2026-08-30):** MVP 323 — probe ~20 Hz · IPC mandos · P1 en `braking/v2/` · horario HUD en
Planning · FSM andén · holgura **OFF** (D9) · señal: diseño S-Lua, probe sin `signal_red` aún · `agent/` (D1) no arrancado.

**Relacionado:** [ARQUITECTURA.md](ARQUITECTURA.md) · [BRAKE_V2.md](BRAKE_V2.md) ·
[HUD_TIMETABLE.md](HUD_TIMETABLE.md) · [TIMEOFDAY_API.md](../reference/TIMEOFDAY_API.md) ·
[CANAL_CONTROL.md](../CANAL_CONTROL.md) · [FREIGHT_NA.md](FREIGHT_NA.md) · [GUIA.md](GUIA.md)

---

## Este doc vs PLAN_V2

| Aquí (referencia) | [PLAN_V2](../v2/PLAN_V2.md) |
| --- | --- |
| Cómo está el probe **hoy** | Qué **debe** cambiar (fases, pasos 1–10) |
| Reglas Lua, campos GetData, log P1 | Debates, criterios de cierre |
| Bitácora de sesiones | Tabla **Deltas** al codificar |

Si hay conflicto, gana **PLAN_V2**.

---

## Foco actual

### Cerrado (referencia — no reabrir salvo regresión)

| Tema | Dónde | Nota |
| --- | --- | --- |
| Velocidad probe ~20 Hz | `tsw_telemetry_source` | Tests `test_speed_*` |
| Mandos IPC | `tsw_ipc_bus` + probe Lua | Preferido frente a teclado |
| P1 frenado | `braking/v2/` → `SpeedDecider` | Sin `archive/braking_v1/` |
| RELEASE cartel+andén | `v2/coordinator.py` + `v2/policy.py` | Política TSW (D5) |
| `station_eta` al plan | `next_stop_arrival` → `station_plan` | No implica holgura ON |
| Horario HUD en GUI | `hud_timetable.py` | Llegada/salida validado |
| Gradiente probe | `gradient_pct` GetData | Una fuente; learner elige celda (§2 PLAN) |
| Un cartel en probe | `dist_limit_cm` / `next_limit_ms` | **Sin** lim2 (TArray revertido) |
| Ventana APPLY física | `v2/physics.py` | [BRAKE_V2.md](BRAKE_V2.md) |
| FSM puertas Lua/DMI | `governor_station.py` | Sin OCR |
| Spawn / DEPARTING / B1 puertas | `governor_station` + policy | 2026-08-28 |
| Cartel lejano aware | `command_from_target` + `physics.py` | No APPLY @ 2+ mi |

### Siguiente trabajo

Ver [v2/PLAN_V2.md § Orden](../v2/PLAN_V2.md#orden-de-implementación) (pasos 1–10) y
[§ Transversal](../v2/PLAN_V2.md#transversal--revisión-tests-y-mantenimiento).

Tarjetas in-game habituales: **C1** (señal Lua) · **C2** (andén) · **F-D** (SD40).

**No reabrir:** señales HTTP tick (D3) · lim2 probe · ámbar/verde en autopilot (D8) · contención `uni=Y` en bajada (2026-08-26).

---

## Probe — reglas (PLAN_V2 §4.1)

- `WRITE_INTERVAL_S = 0.05` (~17–20 Hz); `pcall` en lecturas calientes.
- **No** `pairs(driverAid)` / `pairs(actor)` en `ReceiveTick` (F9 aparte).
- Nuevos campos: escalares (`extract_*`), medir antes de merge.
- **No** reglas P1 ni ritmo en Lua.

Inventario tick hoy: `speed_ms`, power/muescas, frenos HUD, `accel`, `gradient_pct`, un cartel,
puertas, `odo_m`, `brake_cyl_bar` (P1 no usa cilindro §2), IPC ack.

---

## Horario: Planning vs holgura ETA

La pestaña **Planning** y el checkbox **Holgura de horario** no son lo mismo.

| Superficie | Holgura OFF (defecto) | Holgura ON |
| --- | --- | --- |
| GUI Planning: llegada/salida, tabla | Sigue | Igual |
| `station_eta` → P1 (`p1eta=`) | Sí se pasa | Igual |
| Perfil frenado andén | ×1 | Coast / tarde (P-A) |

`schedule_slack=False` por defecto. Reloj = **PC** hasta [TimeOfDay](../reference/TIMEOFDAY_API.md) (D9).
Holgura ON solo con hora de escenario **y** hora de llegada.

Setup BD: [HUD_TIMETABLE.md](HUD_TIMETABLE.md).

---

## FSM estación (referencia 2026-08-28)

Puertas: `_handle_door_service_at_stop` — sin umbral de distancia al tablón.

1. Parado + puertas abiertas → `STOPPED`.
2. Puertas cerradas → `DEPARTING` + `served_bases`.

**Spawn (Lichfield):** `min_distance_m = 0` parado; `SPAWN_PLATFORM_MAX_M` 150 m.
P1 apagado en STOPPED / DEPARTING. Detalle histórico en bitácora.

---

## P1 v2 — log de depuración

Arquitectura: [BRAKE_V2.md](BRAKE_V2.md).

| Pieza | Ruta |
| --- | --- |
| Decisión | `speed_decider.py` → `BrakeCoordinatorV2.evaluate()` |
| Mandos | `handle_controller.py` ← `BrakeCommand` |
| Física | `governor_physics.py` → `v2/physics.py` |
| Horario parada | `next_stop_arrival` → `station_plan.py` |

| Campo log | Significado |
| --- | --- |
| `p1dbg` | SPEED_LIMIT, RELEASE, `p1off:STOPPED`, … |
| `fsm=` | APPROACHING / STOPPED / DEPARTING |
| `uni=Y` / `gap=` | Cartel+andén unificado |
| `p1eta=` | Hora llegada al plan; **no** = holgura ON |
| `arr` / `dep` / `sched` | Claves log horario HUD |

### Señales (estado técnico)

Diseño **S-Lua** cerrado (§3 PLAN). Probe **sin** `signal_red` / `signal_dist_cm`. Python: `is_red_signal_aspect`,
policy, emergencia SIGNAL en coordinator — **stub** `evaluate_signal_brake` hasta pasos 4–5 del plan v2.

Implementación → [v2/PLAN_V2.md](../v2/PLAN_V2.md) fase 4.

---

## Lectura vs escritura

| Capa | Fuente | HTTP |
| --- | --- | --- |
| Tick: vel, mandos, cartel, gradiente, puertas, odo | Probe → GetData | No |
| Mandos | SendCommand.txt IPC | No (mandos) |
| Planning paradas / horario | HTTP + `tsw_hud.db` | Sí (~2 s) |
| TimeOfDay | HTTP poll lento | Sí (D9) |

**No** HTTP para señales en el tick (§3). **No** HTTP para mandos si probe activo.

---

## DynamicHUD (no usar en producción)

| | |
| --- | --- |
| **Sí** | Plantilla UE4SS; referencia `HUD_Get*` / `GetDriverAidData` |
| **No** | No es el probe de producción; no exporta IPC |

**TelemetryProbeMod** es el fork de lectura/escritura IPC. DynamicHUD **desactivado** (`mods.txt : 0`,
sin `enabled.txt` en `DynamicHUDMod`).

---

## Velocidad — congelado (2026-08-22)

Validado ~20 Hz. **No tocar** salvo regresión.

| Regla | Detalle |
| --- | --- |
| Sin caché velocidad | Cada tick lee GetData |
| Planning aparte | No mezclar con lectura speed |
| Tests | `test_speed_*`, `test_tsw_ue4ss_reader.py` |

---

## Gradiente — resuelto

Probe `gradient_pct` ~20 Hz. Learner elige celda; con `using_learned` no doble `g` en `physics.py`
(§2 PLAN). Fallback HTTP lento opcional en `_poll_slow`.

---

## Planning

### Límites — hecho

- Probe: **un** par `dist_limit_cm` / `next_limit_ms`
- lim2 / `NextSpeedLimits[]` en Lua: **aparcado** (UScriptStruct)
- P1: `limit_brake.py` + aware vs APPLY

### Estaciones — planning

- `hud_timetable.py`, `car_stop_signs`, `station_plan.py` (holgura OFF)
- Andén fino (C2): v2 §4.4 — no OCR tablón

### Señales — diseño

- **S-Lua** cerrado; probe sin campos aún — v2 pasos 4–5
- Solo rojo en autopilot (D8: conductor vigila ámbar/verde)

---

## Catálogo probe (prioridad v2)

### En producción (~20 Hz)

`speed_ms`, mandos, `accel`, `gradient_pct`, un cartel, puertas, `odo_m`, `vehicle`, IPC ack.

### Siguiente (con medición §4.1)

| Campo | Para qué | Ref. |
| --- | --- | --- |
| `signal_red` + `signal_dist_cm` | P1 rojo | C1 §3 |
| `is_slipping` (si F9 estable) | Slip → −1 muesca | §2 fase 1 |

### Congelado / no tick (PLAN §2)

- Cilindro / esfuerzo HTTP lento — no P1
- Masa: poll HTTP 5 min (F-B), no por vagón en tick
- Longitud formación — no al plan
- lim2, cola `nextSignals[]` TArray — aparcado

### Poll lento / diagnóstico (no 20 Hz)

Manómetros, `IS_GetBrakeState`, masa formación HTTP — solo si un tren lo demuestra.

---

## Instalación UE4SS (referencia)

- UE4SS v3.0.1 · `TelemetryProbeMod : 1` · DynamicHUD off · Class 323 ~17–20 Hz
- Freight SD40 / estabilidad 10+ min → v2 fase 6 y transversal

IPC: `%TEMP%\TSW6Bridge\GetData.txt` — [CANAL_CONTROL.md](../CANAL_CONTROL.md).

---

## Criterios MVP (canal — snapshot)

| # | Criterio | Estado |
| --- | --- | --- |
| 1–5 | Hz, IPC, P1 límite+estación, mandos | ✅ |
| 6 | Spawn/salida andén | Validar en sesión (transversal) |
| 7 | Señal rojo | v2 pasos 4–5 (C1) |
| 8 | Holgura + TimeOfDay | v2 paso 8 (D9) o OFF |

Detalle de validación → [v2 § Transversal](../v2/PLAN_V2.md#transversal--revisión-tests-y-mantenimiento).

---

## Referencias rápidas

| Recurso | Ruta |
| --- | --- |
| Mod probe | `mods/TelemetryProbeMod/Scripts/main.lua` |
| IPC | `%TEMP%\TSW6Bridge\` |
| Plan | [v2/PLAN_V2.md](../v2/PLAN_V2.md) |

---

## Mandos: IPC vs teclado

IPC primero (`mandos=ipc`); teclado fallback; HTTP PATCH sin UE4SS. Detalle:
`handle_controller.py` · `tsw_ipc_bus.py`.

---

## Bitácora

| Fecha | Qué | Resultado |
| --- | --- | --- |
| 2026-08-18 | Probe 323 | ~17 Hz; gradiente |
| 2026-08-22 | Velocidad | Congelada ~20 Hz |
| 2026-08-23 | HUD horario | `tsw_hud.db`, `car_stop_signs` |
| 2026-08-24 | P1 v2 | Coordinator; llegada/salida GUI |
| 2026-08-26 | FSM puertas | Lua/DMI |
| 2026-08-28 | Andén / spawn | DEPARTING; B1 puertas |
| 2026-08-29 | Cartel lejano | Aware vs APPLY |
| 2026-08-29 | Docs v2 | PENDIENTE alineado [PLAN_V2](../v2/PLAN_V2.md); S-Lua; sin lim2/HTTP señal |

---

## Próximo paso

→ [v2/PLAN_V2.md § Orden](../v2/PLAN_V2.md#orden-de-implementación) y tabla **Deltas**.
