# Plan P1 — actuación MC sin muescas UK

**Estado:** en curso — fase 0 hecha; fase 1a–1c en código (probe `mc_input` + snapshot); pendiente validación in-game.  
**Tren referencia:** M3a MNR (`RVM_NYH_MNR_M3a-B_C`, `data/vehicles/m3a_mnr.json`).  
**Relacionados:** [PLAN_V2 §4.8 / G-B](PLAN_V2.md#48-layout-323-vs-freight) · [CODIGO_V2](CODIGO_V2.md) · [CANAL_CONTROL](../CANAL_CONTROL.md) · [REGLAS_FRENOS_P1](REGLAS_FRENOS_P1.md)

---

## Objetivo

Que trenes **Master Controller** (MC / `IrregularLeverComponent`) usen P1 estación + cartel **sin depender de `lever_notch` UK 323** en telemetría, política ni feedback IPC.

- **P1 interno:** fases de **servicio** (`B1` / `B2` / `B3` / `NEU` / `RELEASE`) y objetivos (STATION, SPEED_LIMIT, SIGNAL).
- **Cable al juego:** solo el **paquete G-B** (`layout` + `brake_input` / `notches[]` + nombres UE).

Las muescas UK (`handle_notch` 3→1, `NEUTRAL_NOTCH=4`) quedan como **implementación del Class 323**, no como contrato universal.

---

## Principio (ya en PLAN_V2)

| Capa | Qué decide | Ejemplo |
| --- | --- | --- |
| **G-A — servicio** | Velocidad objetivo, distancia, defer, FSM andén | `evaluate_station_brake`, `p1_policy` |
| **G-B — layout** | Cómo se escribe el mando en UE | UK: peldaños 323; MC: `InputValue` 0..1 |

**Mal:** `if M3a: … else: muesca 3` repartido en `decision`, `loop`, `p1_station_gate`.  
**Bien:** un traductor `intent → wire` por paquete; política solo ve **estado de cabina** layout-agnóstico.

---

## Estado actual (FACT — código V2)

| Capa | UK 323 (producción) | MC M3a (hoy) |
| --- | --- | --- |
| Plan | `BrakePlanStep.handle_notch`, fases B1–B3 | **Misma** muesca lógica |
| `BrakeTargetResult` | `handle_notch`, `phase` | Igual |
| Comando | `BrakeCommand.target_notch` | + `target_fraction` vía `apply_vehicle_brake_actuator` |
| IPC | `dispatch_step_toward_notch` | `dispatch_to_input_fraction` + rampa `MC_IPC_FRACTION_STEP` |
| Feedback | `lever_notch` | **`probe_mc_input_fraction`** estimado desde muesca UK + cilindro (215905Z) |
| Learner | `decel_by_notch["3"]` | Mismas claves muesca |
| Gates / dwell | `is_brake_applied(lever)`, `combined_lever` | Parches: `brake_applied_from_probe`, dwell sin repetir B1 (075637Z) |

El JSON M3a ya incluye `controls.MasterController.notches[]` con `MinimumInputValue` / `MaximumInputValue` (captura lab). P1 **no** planifica con esa tabla; solo usa `brake_input` como referencia y `mc_service_brake_fraction` (interp. neutro↔B3).

---

## Síntomas de campo (motivación)

| Sesión | OBSERVATION | INFERENCE |
| --- | --- | --- |
| 215007Z | IPC en eje “tracción” del MC | Mapeo B* debe ser &lt; neutro (~0.72) |
| 215905Z | HUD `train_brake` ≠ `InputValue` | Feedback no puede usar solo HUD UK |
| 222115Z | Parado en andén, sin RELEASE | Compuertas RELEASE en aproximación final (corregido) |
| 075637Z | RELEASE P1 pero palanca “bloqueada” | B1 dwell en bucle + IPC sin takeover al soltar MC |

Mientras GetData no exponga **posición real del MC**, takeover y “objetivo alcanzado” siguen siendo frágiles si `lever_notch` no refleja el mando físico.

---

## Contrato interno objetivo (Python V2)

### `ServiceBrakeIntent` (nuevo tipo, fase 0)

Semántica de **servicio**, independiente del layout:

```text
phase: "B1" | "B2" | "B3" | "NEU" | "RELEASE"
strength: float   # opcional 0..1 (redundante con phase; útil para learner)
```

- Los planificadores (`limit_notch`, `station_plan`, `signal_plan`) siguen emitiendo **fase P1**; dejan de ser la fuente de `handle_notch` en rutas MC.
- `BrakeTargetResult` / `BrakePlanStep`: **`service_phase` como fuente de verdad**; `handle_notch` = derivado UK (`uk_layout.py` o propiedad) hasta retirada.

### `BrakeCabState` + `brake_state_from_probe(snap, package)`

Enum layout-agnóstico para política y dwell:

```text
RELEASED | HELD_SERVICE | HELD_EMERGENCY | UNKNOWN
```

**Regla:** `p1_station_gate`, `p1_policy`, `command` (RELEASE heredado) no llaman a `is_brake_applied(lever)` sin pasar por `brake_state_from_probe` cuando hay paquete MC.

### `BrakeCommand`

- Producto MC: `service_phase` + `target_fraction` (rellenado por traductor).
- `target_notch`: legacy UK hasta fase 5.

---

## Telemetría — debate D2 (fase 1)

**UNKNOWN hasta probe:** nombre de clave y precisión en runtime M3a.

| Paso | Entrega | Criterio |
| --- | --- | --- |
| 1a | Lua probe: leer `InputValue` del control del paquete (`MasterController`) | Línea GetData `mc_input=0.XXXX` |
| 1b | `ProbeSnapshot.mc_input` + `parse_probe_line` | [CANAL_CONTROL](../CANAL_CONTROL.md) + fixture pytest |
| 1c | `probe_mc_input_fraction`: **primero** `mc_input`, fallback muesca UK solo si `?` | Test unitario |
| 1d | `loop`: takeover y `_fraction_ipc_target_reached` usan fracción real | Replay 215905Z / 075637Z |

Sin fase 1, las fases 2–3 mejoran el cable pero no cierran “palanca bloqueada” si la telemetría miente.

---

## Actuación — traductor único (fase 2)

Función central (nombre provisional: `intent_to_wire` en `vehicle_package.py` o `actuation.py`):

```text
intent_to_wire(intent: ServiceBrakeIntent, package) → WireCommand
  layout=combined UK  → notch IPC (323)
  layout=master_controller → fraction 0..1
```

- Mapeo MC: preferir `controls.MasterController.notches[]` del JSON cuando esté validado; si no, `mc_service_brake_fraction` (neutro↔B3).
- `loop` solo envía IPC; no recalcula muesca UK en rutas MC.
- Rampa: `MC_IPC_FRACTION_STEP` sin cambio de semántica.

---

## Física y learner (fase 4)

| UK | MC |
| --- | --- |
| `predict_decel(notch, …)` | `predict_decel_service(phase, …)` |
| Perfil `decel_by_notch` | `decel_by_phase` o `decel_by_strength` en `logs/profiles/<vehicle>.json` |

Migración compatible: learner acepta ambas claves según `brake_air.model` / `layout`.

---

## Andén, puertas, gates (fase 3)

- **`combined_lever_for_station_gate`:** en MC, tracción/neutro/freno desde **`mc_input`** y umbrales del paquete (neutro ~0.72), no desde `lever_notch` 0–8.
- **`station_dwell_brake_command`:** condicionar a `BrakeCabState.HELD_SERVICE`, no repetir B1 si ya hay freno de servicio (075637Z).
- FSM `STOPPED` / `DEPARTING`: sin cambio de semántica G-A; solo el **wire** de “freno para puertas” pasa por `intent_to_wire(B1)`.

---

## Fases de entrega

```text
Fase 0 — Contrato Python     ServiceBrakeIntent, BrakeCabState, brake_state_from_probe
Fase 1 — Telemetría D2       mc_input en GetData + snapshot
Fase 2 — Actuación           intent_to_wire; loop MC solo fracción
Fase 3 — Política            gates, dwell, takeover con cab state / mc_input
Fase 4 — Learner             decel por fase en MC
Fase 5 — Limpieza            UK notch solo en uk_layout; planificadores sin handle_notch en MC
```

| Fase | Tests mínimos | Campo |
| --- | --- | --- |
| 0 | Unit; sin cambio comportamiento 323 | — |
| 1 | Fixture GetData; correlación 1 sesión M3a | UE4SS.log + jsonl |
| 2 | `test_loop` MC, `test_vehicle_package` | replay 215905Z |
| 3 | `test_p1_station_gate`, estación Cross-City | 075637Z / sucesora |
| 4 | Perfil M3a; distancias parada ± tolerancia | station mode |
| 5 | Suite completa `V2/tests` | limit + station 323 |

**No en paralelo:** reescribir `limit_notch.py` para MC. UK permanece; MC sale por traductor + telemetría.

---

## Criterios de cierre “M3a sin muescas”

1. Parada en andén Cross-City: soltar freno (P1 RELEASE o manual) sin IPC peleando; feedback usa **`mc_input`**, no inferencia desde `lever_notch`.
2. JSONL: trazas enlazan `service_phase` → `target_frac`; no “muesca 2” como razón de cable.
3. Class 323: `pytest V2/tests` y `run_p1_session limit` sin regresión.
4. D2 actualizado; `handle_notch` en `BrakeTargetResult` documentado como **legacy UK**.

---

## Riesgos

| Riesgo | Mitigación |
| --- | --- |
| `notches[]` del JSON no coincide con variante DLC | Validar con ApiExplorer / F5 por ruta |
| Dos trenes MC | Solo nuevo JSON + perfil; sin forks en `decision.py` |
| Freight / split | Fuera de alcance; `ServiceBrakeIntent` debe extenderse sin romper G-B freight |

---

## Orden de trabajo acordado

1. **Este documento** — plano de referencia (hecho).
2. **Siguiente tarea en código:** elegir una de:
   - **Fase 0** — `BrakeCabState` + `brake_state_from_probe` en dwell/gates MC (orden limpio).
   - **Spike fase 1** — una línea `mc_input=` en probe Lua (desbloquea takeover de forma definitiva).

Recomendación: **fase 0 en paralelo corto con spike 1a** (probe + tipo snapshot), luego fase 2.

---

## Historial

| Fecha | Cambio |
| --- | --- |
| 2026-10-04 | Borrador inicial tras sesiones 222115Z / 075637Z y revisión arquitectura G-A/G-B |
| 2026-10-04 | Fase 0: `brake_cab.py`; dwell + `brake_applied_from_probe` vía `service_brake_held_from_probe` |
| 2026-10-04 | Fase 1a–1c: `mc_input` probe Lua, `ProbeSnapshot`, `probe_mc_input_fraction` prioriza D2 |
| 2026-10-04 | Crash `UE4CC-…57929_0000`: AV en UE4SS; `mc_input` OK en log (build a); probe **b** limita lectura a `MC_VEHICLE_MARKERS`, sin `GetCurrentInputValue` en tick |
