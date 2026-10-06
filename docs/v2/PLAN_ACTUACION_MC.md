# Plan P1 — actuación MC sin muescas UK

**Estado:** en curso — **fase 0** y **1a–1c** validadas (lab/campo); **1d** parcial; **fase 3
andén** avanzada (FSM dwell sin telem puertas, bleed con puertas, salida cono/tail — código + tests,
revalidar M3a en campo); **fase 4 learner** sin arranque (`decel_n=0`, rechazos `pressure` UK en
jsonl M3a); **cierre M3a** §179 #1 sigue parcial (cilindro G1 en dwell).
**Control UK:** Class 323 Cross-City **revalidado en campo** tras fixes COAST / takeover / geometría
señal-andén (usuario **2026-10-04**, sesión **200940Z** — comportamiento general **OK**).
**Tren referencia:** M3a MNR (`RVM_NYH_MNR_M3a-B_C`, `data/vehicles/m3a_mnr.json`).
**Relacionados:** [PLAN_V2 §4.8 / G-B](PLAN_V2.md#48-layout-323-vs-freight) ·
[CODIGO_V2](CODIGO_V2.md) · [CANAL_CONTROL](../CANAL_CONTROL.md) ·
[REGLAS_FRENOS_P1](REGLAS_FRENOS_P1.md)

---

## Objetivo

Que trenes **Master Controller** (MC / `IrregularLeverComponent`) usen P1 estación + cartel **sin
depender de `lever_notch` UK 323** en telemetría, política ni feedback IPC.

- **P1 interno:** fases de **servicio** (`B1` / `B2` / `B3` / `NEU` / `RELEASE`) y objetivos

  (STATION, SPEED_LIMIT, SIGNAL).

- **Cable al juego:** solo el **paquete G-B** (`layout` + `brake_input` / `notches[]` + nombres UE).

Las muescas UK (`handle_notch` 3→1, `NEUTRAL_NOTCH=4`) quedan como **implementación del Class 323**,
no como contrato universal.

---

## Principio (ya en PLAN_V2)

| Capa               | Qué decide                                      | Ejemplo                                 |
|                    |                                                 |                                         |
| **G-A — servicio** | Velocidad objetivo, distancia, defer, FSM andén | `evaluate_station_brake`, `p1_policy`   |
| **G-B — layout**   | Cómo se escribe el mando en UE                  | UK: peldaños 323; MC: `InputValue` 0..1 |

**Mal:** `if M3a: … else: muesca 3` repartido en `decision`, `loop`, `p1_station_gate`.

#### Bien

**Bien:** un traductor `intent → wire` por paquete; política solo ve **estado de cabina

layout-agnóstico.

---

## Estado actual (FACT — código V2)

| Capa                      | UK 323 (producción)                                                           | MC M3a (hoy)                                                                                                                |
| ------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Plan                      | `BrakePlanStep.handle_notch`, fases B1–B3                                     | **Misma** muesca lógica                                                                                                     |
| `BrakeTargetResult`       | `handle_notch`, `phase`                                                       | Igual                                                                                                                       |
| Comando                   | `BrakeCommand.target_notch`                                                   | + `target_fraction` vía `apply_vehicle_brake_actuator`                                                                      |
| IPC                       | `dispatch_step_toward_notch`                                                  | `dispatch_to_input_fraction` + rampa `MC_IPC_FRACTION_STEP`                                                                 |
| Feedback bleed/release MC | `lever_notch`                                                                 | **`mc_input` (D2)** vía `_mc_feedback_fraction`; rampa/cabina: `probe_mc_input_fraction` (D2 → fallback palanca)            |
| Learner                   | `decel_by_notch` + EMA v1; `brake_decel_sample_ready` (palanca UK + bar ~1.6) | **Sin perfil** — plan usa `DEFAULT_MAX_BRAKE_DECEL`; muestras bloqueadas (FACT **212610Z**: 12× `learn` rechazo `pressure`) |
| Gates / dwell             | `is_brake_applied(lever)`, `combined_lever`                                   | Bleed MC + FSM `STOPPED` mid-route ~35 m; `combined_lever_for_station_gate` aún **`power`** (fase 3 pendiente)              |

El JSON M3a incluye `controls.MasterController.notches[]` (lab). **Cable P1:** peldaños
`brake_input` (`mc_fraction_for_plan_handle`); `mc_service_brake_fraction` solo fallback si falta
clave.

---

## Síntomas de campo (motivación)

| Sesión  | OBSERVATION                         | INFERENCE                                            |
| ------- | ----------------------------------- | ---------------------------------------------------- |
| 215007Z | IPC en eje “tracción” del MC        | Mapeo B* debe ser &lt; neutro (~0.72)                |
| 215905Z | HUD `train_brake` ≠ `InputValue`    | Feedback no puede usar solo HUD UK                   |
| 222115Z | Parado en andén, sin RELEASE        | Compuertas RELEASE en aproximación final (corregido) |
| 075637Z | RELEASE P1 pero palanca “bloqueada” | B1 dwell en bucle + IPC sin takeover al soltar MC    |

Con probe **20261004d**, GetData expone `mc_input` en M3a (FACT: jsonl 095249Z / 105359Z). Takeover
/ `target_reached` en **loop** siguen pudiendo usar estimación por palanca si D2 falta un tick.

---

## Validación acumulada (2026-10-04)

| Ámbito      | Qué                                                      | Estado                                                                                                                                            |
| ----------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Lab         | Fase 0, 1b–1c, cable 0.64, bleed gates (081821Z–105359Z) | **OK** — `pytest V2/tests`                                                                                                                        |
| Campo       | `mc_input` en jsonl                                      | **OK** post-20261004d; **090412Z** = null (probe c)                                                                                               |
| Campo       | `target_frac` 0.64 en `platform_bleed`                   | **OK**                                                                                                                                            |
| Campo       | Ciclo bleed sin ping-pong                                | **OK** **111522Z** — 4 transiciones bleed↔release en ~9k ticks; sin 0.64↔0.69 en bucle (vs 105359Z / 110400Z)                                     |
| Campo       | `brake_cyl_bar` ↓ en dwell bleed                         | **Pendiente** — **111522Z** ~9.5→11.2 bar en andén (MC en B1/B2 manual; no evidencia de sangrado en G1)                                           |
| Lab         | 1d loop takeover / target_reached solo D2                | **Pendiente**                                                                                                                                     |
| Lab/campo   | Criterio cierre §179 #1 completo                         | **Parcial** — **111522Z** 1ª parada: APPLY B1 → `no_plan`/`tf=None` → RELEASE neutro 0.72 (`mc_input` 0.72); 2ª parada cortada en log sin RELEASE |
| Campo       | Class 323 estación Cross-City (no MC)                    | **OK** usuario — **200940Z** Four Oaks; sin regresión percibida tras cambios P1 recientes                                                         |
| Campo       | M3a origen / match paquete + RELEASE huérfano            | **OK** código — **210508Z** (match `RVM_NYH_MNR_M3a`, planning IPC)                                                                               |
| Campo       | Planning HTTP ruta ajena + bleed fantasma                | **Mitigado** — `station_planning_trusted` (**211320Z**); crash UE4SS aparte                                                                       |
| Campo       | Parada sin `STOPPED` / ping-pong bleed en dwell          | **Código** — **212610Z** motivó FSM + supresión bleed puertas; **pendiente** jsonl con `stn_fsm=STOPPED` y sin ping-pong                          |
| Campo / lab | Learner M3a (`decel_observe_n`, perfil guardado)         | **Pendiente** — **212610Z** `decel_n=0`, `brake_fill_n=0`; perfil auto-save sin JSON útil en repo                                                 |

---

## Contrato interno objetivo (Python V2)

### `ServiceBrakeIntent` (nuevo tipo, fase 0)

Semántica de **servicio**, independiente del layout:

```text
```

- Los planificadores (`limit_notch`, `station_plan`, `signal_plan`) siguen emitiendo **fase P1**;

  dejan de ser la fuente de `handle_notch` en rutas MC.

- `BrakeTargetResult` / `BrakePlanStep`: **`service_phase` como fuente de verdad**; `handle_notch` =

  derivado UK (`uk_layout.py` o propiedad) hasta retirada.

### `BrakeCabState` + `brake_state_from_probe(snap, package)`

Enum layout-agnóstico para política y dwell:

```text
```

**Regla:** `p1_station_gate`, `p1_policy`, `command` (RELEASE heredado) no llaman a
`is_brake_applied(lever)` sin pasar por `brake_state_from_probe` cuando hay paquete MC.

### `BrakeCommand`

- Producto MC: `service_phase` + `target_fraction` (rellenado por traductor).
- `target_notch`: legacy UK hasta fase 5.

---

## Telemetría — debate D2 (fase 1)

**UNKNOWN hasta probe:** nombre de clave y precisión en runtime M3a.

| Paso | Entrega                                                                           | Criterio                                                                 |
| ---- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 1a   | Lua probe: leer `InputValue` del control del paquete (`MasterController`)         | Línea GetData `mc_input=0.XXXX`                                          |
| 1b   | `ProbeSnapshot.mc_input` + `parse_probe_line`                                     | [CANAL_CONTROL](../CANAL_CONTROL.md) + fixture pytest                    |
| 1c   | `probe_mc_input_fraction`: **primero** `mc_input`, fallback muesca UK solo si `?` | Test unitario                                                            |
| 1d   | `loop`: takeover y `_fraction_ipc_target_reached` usan fracción real              | Replay 215905Z / 075637Z — bleed MC **solo D2** (FACT); loop **parcial** |

Sin fase 1, las fases 2–3 mejoran el cable pero no cierran “palanca bloqueada” si la telemetría
miente.

---

## Actuación — traductor único (fase 2)

Función central (nombre provisional: `intent_to_wire` en `vehicle_package.py` o `actuation.py`):

```text
```

- Mapeo MC: preferir `controls.MasterController.notches[]` del JSON cuando esté validado; si no,

  `mc_service_brake_fraction` (neutro↔B3).

- `loop` solo envía IPC; no recalcula muesca UK en rutas MC.
- Rampa: `MC_IPC_FRACTION_STEP` sin cambio de semántica.

---

## Física y learner (fase 4)

| UK                                        | MC                                                                                                              |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `predict_decel(notch, …)`                 | `predict_decel_service(phase, …)`                                                                               |
| Perfil `decel_by_notch`                   | `decel_by_phase` o `decel_by_strength` en `logs/profiles/<vehicle>.json`                                        |
| `brake_decel_sample_ready(lever, bar UK)` | Confirmar fase con **`mc_input` vs `brake_input`**; no exigir `lever_notch` HUD                                 |
| Fill-time EMA                             | **Opcional en MC** — reposo ~10 bar; L4 ya bypass (`air_ready` MC). No bloquear cierre M3a por `brake_fill_n=0` |

Migración compatible: learner acepta ambas claves según `brake_air.model` / `layout`.

### Entregas fase 4 (orden interno)

1. **4a — Gate de muestra MC** — `brake_decel_sample_ready` (o hermana) con

   `BrakeAirProfile.master_controller` + `probe_mc_input_fraction` / bandas B1–B3 del paquete; usada
   por **learner** y **`brake_feedback`** (misma fuente que UK).

2. **4b — Spike campo** — sesión corta **modo limit** (cartel 35→20 mph, poco andén);

   `analyze_learner_jsonl.py` con `learn accepted > 0`, `decel_observe_n` creciente, `fb` con
   pred/obs.

3. **4c — Claves de perfil** — persistir `decel_by_phase` (B1/B2/B3) en

   `logs/profiles/rvm_nyh_mnr_m3a-*.json`; `LearnerProfile.predict_decel` enruta por `layout` / fase
   servicio.

4. **4d — Semilla opcional** — valores lab o sesión buena en JSON vehículo o perfil; evita plan UK

   puro mientras EMA &lt; `MIN_SAMPLES`.

5. **4e — Criterio “sólido”** — distancias cartel/estación dentro de tolerancia acordada + `pytest`

   MC learner + **323 sin regresión**; no solo “deja de rechazar pressure”.

**No confundir** con paquete G-B (`brake_input` 0.64…): eso ya alimenta IPC; fase 4 es **física de
planificación** (decel observada).

---

## Andén, puertas, gates (fase 3)

- **`combined_lever_for_station_gate`:** en MC, tracción/neutro/freno desde **`mc_input`** y

  umbrales del paquete (neutro ~0.72), no desde `lever_notch` 0–8.

- **`station_dwell_brake_command`:** condicionar a `BrakeCabState.HELD_SERVICE`, no repetir B1 si ya

  hay freno de servicio (075637Z).

- FSM `STOPPED` / `DEPARTING`: sin cambio de semántica G-A; solo el **wire** de “freno para puertas”

  pasa por `intent_to_wire(B1)`.

---

## Fases de entrega

```text
```

| Fase | Tests mínimos                               | Campo               |
| ---- | ------------------------------------------- | ------------------- |
| 0    | Unit; sin cambio comportamiento 323         | —                   |
| 1    | Fixture GetData; correlación 1 sesión M3a   | UE4SS.log + jsonl   |
| 2    | `test_loop` MC, `test_vehicle_package`      | replay 215905Z      |
| 3    | `test_p1_station_gate`, estación Cross-City | 075637Z / sucesora  |
| 4    | Perfil M3a; distancias parada ± tolerancia  | station mode        |
| 5    | Suite completa `V2/tests`                   | limit + station 323 |

**No en paralelo:** reescribir `limit_notch.py` para MC. UK permanece; MC sale por traductor +
telemetría.

---

## Criterios de cierre “M3a sin muescas”

1. Parada en andén Cross-City: soltar freno (P1 RELEASE o manual) sin IPC peleando; feedback usa

   **`mc_input`**, no inferencia desde `lever_notch`. — **Parcial:** **111522Z** confirma D2 + ciclo
   estable; largo dwell en `platform_bleed_release` (razón sin `cmd`) antes del RELEASE; cilindro no
   baja en dwell.

2. JSONL: trazas enlazan fase servicio → `target_frac` (`p1.phase` hoy); no “muesca 2” como razón de

   cable. — **Parcial** en campo (`phase=B1`, `target_frac=0.64`).

3. Class 323: `pytest V2/tests` y `run_p1_session limit` sin regresión. — **OK** (lab + campo

   estación **200940Z**, usuario).

4. D2 actualizado; `handle_notch` en `BrakeTargetResult` documentado como **legacy UK**. —

   **Parcial** (`CANAL_CONTROL`; plan §32–44 al día).

---

## Riesgos

| Riesgo                                            | Mitigación                                                                    |
| ------------------------------------------------- | ----------------------------------------------------------------------------- |
| `notches[]` del JSON no coincide con variante DLC | Validar con ApiExplorer / F5 por ruta                                         |
| Dos trenes MC                                     | Solo nuevo JSON + perfil; sin forks en `decision.py`                          |
| Freight / split                                   | Fuera de alcance; `ServiceBrakeIntent` debe extenderse sin romper G-B freight |

---

## Orden de trabajo acordado

Prioridad **antes** de fase 4 completa: andén estable en campo; luego cartel + learner.

| #     | Bloque                                  | Entrega                                                                               | Criterio de hecho                                                                                                     |
| ----- | --------------------------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **A** | **Campo andén M3a**                     | Re-run Cross-City station tras fixes **212610Z** (FSM, bleed puertas, RELEASE salida) | jsonl: `stn_fsm=STOPPED` en parada; sin ping-pong `platform_bleed*` en dwell; RELEASE salida tras marker / fuera cono |
| **B** | **Cierre §179 #1 residual**             | Cilindro / bleed útil en dwell                                                        | Evidencia `brake_cyl_bar` o G1 (si probe) — **111522Z** aún ambiguo                                                   |
| **C** | **1d loop**                             | Takeover + `_fraction_ipc_target_reached` solo D2                                     | Tests `test_loop` MC; sin takeover por palanca UK errónea                                                             |
| **D** | **Fase 3 gates**                        | `combined_lever_for_station_gate` desde `mc_input`                                    | `test_p1_station_gate`; DEPARTING sin falsa tracción por `power`                                                      |
| **E** | **Fase 4a–4b**                          | Gate muestra MC + 1 sesión limit                                                      | `decel_observe_n > 0`; analyzer sin 100 % `pressure`                                                                  |
| **F** | **Fase 4c–4e**                          | Perfil `decel_by_phase` + validación distancias                                       | Perfil en `logs/profiles/`; cartel/estación dentro tolerancia                                                         |
| **G** | **Fase 2 formal** (puede esperar a E–F) | `intent_to_wire`, `service_phase` en jsonl                                            | Trazabilidad cable; no bloquea A–E                                                                                    |

**Hecho reciente (lab, pendiente campo A):** match M3a (**210508Z**), planning trust (**211320Z**),
dwell FSM/bleed/salida (**212610Z** — ver [REGLAS_FRENOS_P1](REGLAS_FRENOS_P1.md)).

**Fuera de alcance MC (estación Cross-City UK):** crawl aproximación **200940Z** — backlog límite 20
mph; geometría señal-andén en `signal_plan`.

### Siguiente acción concreta (recomendada)

1. Sesión **station** M3a GCT con build actual → validar fila **A** del tabla.
2. Si **A** OK → implementar **4a** + pytest (sin tocar planificadores UK).
3. Sesión **limit** 15–20 min → fila **E**; solo entonces perfil **F**.

---

## Historial

| Fecha      | Cambio                                                                                                                                                                                          |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-10-04 | Borrador inicial tras sesiones 222115Z / 075637Z y revisión arquitectura G-A/G-B                                                                                                                |
| 2026-10-04 | Fase 0: `brake_cab.py`; dwell + `brake_applied_from_probe` vía `service_brake_held_from_probe`                                                                                                  |
| 2026-10-04 | Fase 1a–1c: `mc_input` probe Lua, `ProbeSnapshot`, `probe_mc_input_fraction` prioriza D2                                                                                                        |
| 2026-10-04 | Crash `UE4CC-…57929_0000`: AV en UE4SS; `mc_input` OK en log (build a); probe **b** limita lectura a `MC_VEHICLE_MARKERS`, sin `GetCurrentInputValue` en tick                                   |
| 2026-10-04 | Sesión **090412Z**: `mc_input` null (solo `InputValue`); probe **20261004d** lee `CurrentInputValue` + resolución control como IPC                                                              |
| 2026-10-04 | Cable `brake_input` peldaños; bleed MC: `suppress_reapply`, confirmación B1 (`PLATFORM_BLEED_B1_CONFIRM_TICKS`); sesiones 095249Z / 105359Z                                                     |
| 2026-10-04 | Sesión **111522Z** (git f5e7d44, probe **20261004d**): `mc_input` 9006/9014 ticks; 2 paradas; APPLY B1×2; 1 RELEASE a neutro; sin ping-pong; UE4SS `ack_timeout` en RELEASE id 38–39 luego `ok` |
| 2026-10-04 | Sesión **114756Z**: COAST sin soltar MC — fix loop: no takeover por `power` hacia neutro; `COAST_THROTTLE` atraviesa cooldown manual; actuator MC + tracción vía `mc_input`                     |
| 2026-10-04 | Cooldown manual override retirado (`loop`); takeover = `clear_target()` sin timer                                                                                                               |
| 2026-10-04 | Sesión **200940Z** (Class 323, Four Oaks): análisis aproximación; fix `stn < sig` → defer STATION / `signal_in_play` false (no parada al poste de salida)                                       |
| 2026-10-04 | Usuario: vuelta al **323** en campo tras fixes — estación Cross-City **OK** (regresión UK cerrada para seguir con M3a)                                                                          |
| 2026-10-04 | **210508Z** / **211320Z**: match paquete M3a-A; guard planning HTTP; doc REGLAS                                                                                                                 |
| 2026-10-04 | **212610Z**: dwell sin telem puertas, bleed con puertas, `departing_ipc_release_allowed`, `platform_tail_m` M3a; learner sigue en 0 (rechazo `pressure`)                                        |
| 2026-10-04 | Plan: orden A→G; fase 4 desglosada 4a–4e; learner MC no bloquea cierre por `brake_fill_n`                                                                                                       |
