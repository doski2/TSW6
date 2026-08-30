# Paridad Dastsc — TSW6 ↔ Nexus V4 (Dastsc)

**Objetivo:** mismo comportamiento de frenado que `C:\Users\doski\Dastsc` (nexus-agent + commandBus

+ IPC).

Trabajo en paralelo: cambios de algoritmo en Dastsc se portan aquí; cambios de probe/TSW API solo en
TSW6.

**P1 activo:** ver [BRAKE_V2.md](BRAKE_V2.md). Todo en `tsw6/braking/v2/`.

**Comparativa paso a paso (SVG):** [COMPARATIVA_DASTSC_FLUJO.md](COMPARATIVA_DASTSC_FLUJO.md)

**Dastsc — diagrama espejo:** `C:\Users\doski\Dastsc\docs\FLUJO_FRENOS_V4.md` ·

`C:\Users\doski\Dastsc\docs\flujo_frenos_v4.svg`

---

## Arquitectura Dastsc (referencia)

```text
```

Código: `nexus-agent/src/tick.ts`, `brake/planBrake.ts`, `command/commandBus.ts`.
Árbol: `C:\Users\doski\Dastsc\docs\FLUJO_FRENOS_V4.md`.

**UI:** React V4 (5175) — no está en el loop de latencia crítica (localhost).

**Sin** COAST/BRAKE genéricos en P1: el plan devuelve **B1/B2/B3** (o % Acela) y el bus escribe el

**notch absoluto**.

---

## Arquitectura TSW6 (actual)

```text
```

FSM (`governor_station`) vuelve a preguntar `station_waits` / `merged_approach`.
Eso **no** es el split Dastsc (un RELEASE, cluster = filtrar STATION).

**UI:** `autopilot_gui.py` (tkinter) **en el mismo proceso** — más directo que V4+WS; mismo IPC

archivo hacia el juego.

Ver [FLUJO_FRENOS.md](FLUJO_FRENOS.md) · [ESTADO.md](ESTADO.md)

---

## Reglas de conducción (revisión 2026-08-29)

Lo que hay que **portar de Dastsc es el corte de responsabilidades**, no un copiar-pegar del `.ts`.
TSW6 tiene HUD DriverAid, FSM UK y casos Cross-City (Four Oaks / Sutton) que Dastsc no modela.

| Pregunta | Dastsc | TSW6 hoy | Propuesta |
| --- | --- | --- | --- |
| ¿Quién gana cartel vs andén? | Cluster: **quitar STATION del pool** si cartel **antes** y gap ≤ 350 m | `uni=Y` + `should_delay` + `skip_defer` + `station_waits` | Misma idea de cluster que Dastsc; **más** `station_waits` si el recorte está *después* del andén (Four Oaks) |
| ¿Cuándo hay plan andén? | `dist < stationPlanHorizonM` (B1×1,15) | `should_defer` (v→0 servicio +25 m) **o** `should_emit` B1 | Una sola: horizonte de servicio para *emitir*; el B1 no abre STATION a 800 m |
| ¿RELEASE? | **Una** `resolveReleaseAction` al empezar el mando | Coordinador al inicio **y** `command_from_target`; atajo `uni=Y` puede saltarse el hold de bajada | Una función; el atajo `uni=Y` no anula bajada |
| ¿Bajada + cartel? | Gradiente &lt; −3 ‰ y hay next → **nunca OFF**; muesca más fuerte; sin coast-latch | Hold hasta ~8 m del cartel si `spd` sigue alta | Estructura Dastsc (un sitio). Política: **hold 8 m**, no “nunca soltar” (en Cross-City soltaba demasiado tarde o el atajo demasiado pronto) |
| Margen RELEASE | ~2 mph (perfil) | 0,4 mph | Dejar 0,4 (UK 323); no copiar 2 mph |
| HUD invertido | `shouldMerge` falso → los dos planes compiten | `station_waits` / `skip_defer` | Conservar reglas TSW; no están en Dastsc |

**No** borrar `braking/v2/` y reescribir desde el `.ts`. Motores (`physics`, perfil B1–B3, IPC, FSM)
se quedan. Orden de trabajo: [BRAKE_V2 — Cómo tocar
reglas](BRAKE_V2.md#cómo-tocar-reglas-sin-borrar-v2).

---

## Estado paridad (2026-08-29)

### Hecho en ambos

| Pieza | TSW6 | Dastsc |
| --- | --- | --- |
| IPC GetData/SendCommand | `tsw_ue4ss_reader`, `tsw_ipc_bus` | Lua + `command_bus.py` |
| P1 límite + estación + prioridad | `braking/v2/` | `planBrake.ts` + `selectUrgentBrakePlan` |
| Comando notch directo P1 | `v2/command.py` + `HandleController` | `commandBus.buildBrakeCommand` |
| RELEASE al objetivo | `v2/command.py` | `resolveReleaseAction` (P1.6 effective) |
| Anti-rebrake (coast latch) | `BrakeReleaseState` | `shouldInhibitLimitRebrake` |
| Gradiente en distancia freno | `v2/physics.py` (`gradient_pct`) | `gravityAcceleration` (‰) + signo manual V4 |
| Ventana APPLY (metros) | `apply_zone_margin_m` (vel + `apply_at`, sin 60 m fijo) | Zona effective en plan |
| Decel por muesca (aprendida) | `OnlineLearner` | `brakeStats` + **bandas H/M/B** (P3.7) |
| Cluster cartel+andén | `uni` + waits + defer (no es el filtro Dastsc) | filtrar STATION si merge |
| RELEASE único | No (coordinador + `command` + atajo `uni=Y`) | Sí: `resolveReleaseAction` |
| Horario / paradas comerciales | `hud_timetable.py` + `tsw_hud.db` | OCR + `station_distance.py` |
| Documentación flujo SVG | `esqueleto_flujo_cronologico.svg` | `flujo_frenos_v4.svg` (15 pasos) |

### Solo Dastsc (referencia para port)

| Pieza | Notas |
| --- | --- |
| `planBrakeForSignal` con telemetría señal | TSW: stub — falta distancia señal en GetData |
| `massFactor(massT)` sin stats | TSW: peso implícito en learner |
| Modos SUGGEST / ARM / AUTO | TSW: GUI conducción manual + autopilot |
| Log sesión JSON (`tick_change`, gradientPct) | TSW: log texto `autopilot_*.log` |
| Effort/BC Acela (Lua v12) | TSW: según probe DynamicHUD |
| Guards BC al soltar OFF (P3.6) | Pendiente ambos |

### Solo TSW6 (extra)

| Pieza | Notas |
| --- | --- |
| SafetyWatchdog exceso persistente | Teclado BRAKE_FAST |
| FSM estación UK (puertas Lua/DMI, creep) | Más maduro en TSW; OCR no entra en FSM |
| Marcador freno DMI advisory | |
| Solo-frenado (sin ACCELERATE auto) | |
| GUI Acción `B2 →N2` en barra | Referencia UX |

---

## En curso / siguiente

| Pieza | Prioridad | Proyecto |
| --- | --- | --- |
| **Límites: un RELEASE + hold bajada (sin atajo uni)** | Alta | TSW6 — fase 1 reglas |
| **Andén: un horizonte (no B1 gordo vs defer)** | Alta | TSW6 — fase 2 |
| **Cluster Dastsc + waits Four Oaks** | Alta | TSW6 — fase 3 |
| `evaluate_signal_brake` con distancia DANGER | Media | TSW6 (telemetría) |
| Recalcular distancia tablón cada tick | Media | TSW6 |
| Perfil por tren (`agent_config` JSON) | Media | Ambos |
| Perfiles semilla UK EMU | Media | TSW6 — [FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md) |
| **Masa tren (`massT`) en física P1** | Baja freight | Port Dastsc → TSW6 |
| Freight split-brake | Baja | Ambos |
| Modos ARM/AUTO estilo Dastsc | Baja | TSW6 GUI |
| Payload slim / agente en backend | Baja | Dastsc — menos hops, no más GUI |

---

## Masa del tren — gap de paridad

**Dastsc** escala la deceleración sin stats aprendidas:

```text
```

**TSW6** no lee masa ni aplica `massFactor`. Usa `decel_for_notch()` + gradiente y

`OnlineLearner.predict_brake_decel()` — el peso queda **implícito** en muestras.

**Base unificada (2026-08-25):** `DEFAULT_MAX_BRAKE_DECEL` en `v2/physics.py` =

`MAX_DECEL_MS2` en `governor_constants` (1.071 m/s²).

| Situación | ¿Basta sin `massT`? |
| --- | --- |
| Class 323 UK + perfil aprendido | ✅ MVP actual |
| Cambiar carga sin re-aprender | ⚠️ Desvío posible |
| SD40-2 freight vacío/cargado | ❌ Conviene `massFactor` o masa UE |

Telemetría futura TSW: `GetMassOfCargo` — [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md).

---

## Pipeline P1 actual (v2)

```text
```

Sin plan P1: `HOLD` (watchdog teclado si exceso persistente).

**Ventana APPLY (2026-08-26):** `apply_zone_margin_m` sustituye umbrales fijos (60 m APPLY,
80/30 m histeresis cartel, 150 m contención bajada). Ver [BRAKE_V2.md](BRAKE_V2.md).

Equivalente Dastsc: pasos **8–14** en `flujo_frenos_v4.svg`.

---

## Cómo validar in-game

#### TSW6

1. `install_ue4ss_probe.bat` + reiniciar GUI
2. Acercarse a límite más bajo con tracción manual
3. Depuración: `v2 SPEED_LIMIT B2 distStart=…`
4. Acción: `B2 →N2` (notch absoluto)
5. Handle en **un** ciclo IPC (~50 ms), no 5 pasos

#### Dastsc

1. `Iniciar_Nexus_V4.bat` — backend + V4
2. Modo AUTO o ARM — Class 323 / Acela según escenario
3. Log: `logs/nexus-v4/session_*.json` — `tick_change`, `agent.headline`
4. Ver [Dastsc/docs/debug/README.md](../README.md)

---

## Tests regresión

```bat
```

Dastsc:

```bat
```

---

## Referencia cruzada de código

| Dastsc | TSW6 |
| --- | --- |
| `nexus-agent/src/brake/planBrake.ts` (`planBrakeForLimit` / `Station` / `selectUrgent`) | `limit_brake.py` / `station_plan.py` / `policy.py` |
| `nexus-agent/src/command/commandBus.ts` (`resolveReleaseAction`) | `v2/command.py` (hoy también RELEASE en `coordinator.py`) |
| `nexus-agent/src/tick.ts` | `autopilot_core.py` + `speed_decider.py` + `coordinator.py` |
| `Dastsc-V3/backend/core/command_bus.py` | `tsw_ipc_bus.py` |
| `Dastsc-V4/hooks/useAutoCommand.ts` | `handle_controller.py` |
| `nexus-kernel/TelemetryHub.ts` | `tsw_telemetry_source.py` + `train_state.py` |
| OCR estación (`station_distance.py`) | HUD DB + HTTP TrackData |
| Horario (V4 no tiene equivalente) | `hud_timetable.py` — [HUD_TIMETABLE.md](HUD_TIMETABLE.md) |
