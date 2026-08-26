# Comparativa de flujo — TSW6 ↔ Nexus V4 (Dastsc)

**Objetivo:** mismo número de paso en cada diagrama para estudiar y portar algoritmos.

| Proyecto | Diagrama | Ruta |
| --- | --- | --- |
| **TSW6** | [assets/esqueleto_flujo_cronologico.svg](assets/esqueleto_flujo_cronologico.svg) | `C:\Users\doski\TSW6` |
| **Dastsc** | [FLUJO_FRENOS_V4.md](file:///C:/Users/doski/Dastsc/docs/FLUJO_FRENOS_V4.md) + [flujo_frenos_v4.svg](file:///C:/Users/doski/Dastsc/docs/flujo_frenos_v4.svg) | `C:\Users\doski\Dastsc` |

**Última revisión:** 2026-08-26

---

## Resumen arquitectónico

| Aspecto | TSW6 | Nexus V4 (Dastsc) |
| --- | --- | --- |
| Sim | Train Sim World 6 + UE4SS | Train Simulator Classic + Lua plugin |
| UI | **GUI tkinter** en el mismo proceso Python | **React** (puerto 5175) + WebSocket |
| Telemetría rápida | Probe ~20 Hz → `%TEMP%\TSW6Bridge\GetData.txt` | Lua ~10–20 Hz → `plugins\GetData.txt` |
| Fusión lenta | HTTP DriverAid + `tsw_hud.db` | OCR backend + `station_distance.py` |
| Paso “bus” | **No hay WS** — `dict` en memoria (`_telem`) | **WebSocket** `:8000/ws` → V4 |
| Decisión | `autopilot_core` + `speed_decider` | `tickAgent` + `PolicyMode` |
| Plan freno | `BrakeCoordinatorV2` (v2/) | `planBrake.ts` + `selectUrgentBrakePlan` |
| Mando | `tsw_ipc_bus` → `SendCommand.txt` | `command_bus.py` → `SendCommand.txt` |
| Aprendizaje | `OnlineLearner` / `predict_decel` | `brakeStats` + bandas H/M/B (P3.7) |
| Log sesión | `logs/autopilot_*.log` | `logs/nexus-v4/session_*.json` |

**TSW6 es más directo** en lectura→decisión (un proceso + GUI). **Dastsc** separa kernel/agente/UI y
añade WS + log estructurado — no suele ser el cuello de botella (localhost); el IPC **archivo**
Lua↔Python es común a ambos.

---

## Mapa paso a paso (numeración SVG)

Use esta tabla al estudiar. Los colores del encabezado coinciden con ambos SVG.

| Paso | Bloque | TSW6 | Dastsc Nexus V4 | |
| --- | --- | --- | --- | --- |
| **1** | LECTURA | `main.lua` UE4SS — HUD + DriverAid → GetData TSV | `Railworks_GetData_Script.lua` — controles TSC → GetData `\ | ` |
| **2** | LECTURA | `tsw_ue4ss_reader.py` — `ProbeSnapshot` | `main.py` `parse_telemetry_line` + OCR/cab enrich | |
| **3** | LECTURA / bus | `tsw_telemetry_source.py` — merge probe+HTTP+HUD → `_telem` | **WebSocket `TELEMETRY`** — `broadcast()` → V4 | |
| **4** | CICLO | `autopilot_core.tick()` | `TelemetryHub.ingestMessage` + `DataNormalizer` | |
| **5** | CICLO | `build_train_state()` → `TrainState` | `toTelemetrySnapshot` + `useBrakeStats` | |
| **6** | DECISIÓN | `speed_decider.decide()` — FSM → P1 / HOLD | `tickAgent()` — horizon + plan wrapper | |
| **7** | DECISIÓN | (dentro de decider) guardias P1 / watchdog | `PolicyMode` + `blockedReason` AUTO | |
| **8** | PLAN | `coordinator` — limit / station / planner (+ signal stub) | `planBrakeForLimit` / `Station` / `Signal` | |
| **9** | PLAN | prioridad + cluster | `selectUrgentBrakePlan` | |
| **10** | PLAN | `decel_for_notch` + gradiente % | `decelForNotch` + gradiente ‰ + stats banda v | |
| **11** | PLAN / decisión | RELEASE + coast latch | `resolveReleaseAction` (+ P3.6 BC pendiente Dastsc) | |
| **12** | EJECUCIÓN | `BrakeCommand` → notch absoluto | `AgentAction` — `commandBus.buildBrakeCommand` | |
| **13** | EJECUCIÓN | `handle_controller.execute()` | `useAutoCommand` / ARM confirm → WS `COMMAND` | |
| **14** | EJECUCIÓN | `tsw_ipc_bus` → SendCommand | `command_bus.py` → SendCommand + flag | |
| **15** | JUEGO | `main.lua` aplica PowerBrakeHandle | Lua `SendData()` — VirtualBrake / ThrottleAndBrake | |

Dastsc tiene **paso 15** explícito en el SVG; TSW6 cierra en **14** (vuelta al tick 1).

---

## Paridad de algoritmo (frenado P1)

| Concepto | TSW6 | Dastsc | Notas |
| --- | --- | --- | --- |
| Muescas B1–B3 | `v2/command.py` | `commandBus.notchToBrakeValue` | Notch absoluto IPC |
| RELEASE al objetivo | `v2/command.py` | `resolveReleaseAction` | Dastsc P1.6: `limits.effective` |
| Coast latch UK | `BrakeReleaseState` | `shouldInhibitLimitRebrake` | |
| Cluster cartel+andén | `cluster.py` | `<350 m` excluye plan estación | |
| Prioridad | `priority.py` | Señal → Límite → Estación | |
| Gradiente en plan | `gradient_pct` | ‰ + botón **+/−** manual V4 | TSW: probe DriverAid |
| Ventana APPLY | `apply_zone_margin_m` (física) | effective zone en plan | TSW6: sin 60 m fijo (2026-08-26) |
| Stats aprendidas | `OnlineLearner` | `brakeStats` por banda H/M/B | Dastsc P3.7 |
| Effort / BC feedback | probe limitado | Lua v12 + log `brake.tractiveKn` | Dastsc P3.5/P3.6 |
| Señal DANGER | **stub** (sin distancia en GetData) | `planBrakeForSignal` ✅ | Port pendiente TSW |
| Masa `massFactor` | ❌ implícito en learner | ✅ `massT/500` sin stats | Ver [DASTSC_PARITY.md](DASTSC_PARITY.md) |
| Modos SUGGEST/ARM/AUTO | GUI manual (sin ARM separado) | SUGGEST / ARM / AUTO | |

---

## Dastsc — cambios recientes (2026-08-17 … 25)

Para no desincronizar la paridad al comparar:

| Cambio Dastsc | Doc |
| --- | --- |
| Árbol frenado V4 + SVG 15 pasos | `Dastsc/docs/FLUJO_FRENOS_V4.md`, `flujo_frenos_v4.svg` |
| `brakeStats` banda velocidad (high/med/low) | P3.7 en `PENDIENTES_V4.md` |
| Gradiente manual +/− UI | `NEXUS_V4_ARQUITECTURA.md` §4.5 |
| Lua v12 Effort/BC Acela | `ESPECIFICACION_ULTRA_CORE_V4.md` |
| Log sesión `gradient`, `gradientPct`, effort | `debug/README.md` |
| Tipos freno SPLIT/blended | `TIPOS_DE_FRENOS.md` |
| Fix OFF zona límite (effective) | P1.6 validado |

---

## Qué portar en cada dirección

#### Dastsc → TSW6

- Guards BC al soltar OFF (cuando haya telemetría cilindro en probe).
- `massFactor(massT)` en `decel_for_notch` si se expone masa UE.
- Filtrar learning por calidad de muestra (Plan B Effort).

#### TSW6 → Dastsc

- FSM estación UK (puertas, creep) — parcial en Dastsc vía OCR.
- Parada unificada cartel+andén (`_should_block_limit_release`).
- GUI “Acción” compacta (B2→N2) — referencia UX, no arquitectura.

---

## Estudio recomendado

1. Mismo paso en ambos SVG (esta tabla).
2. TSW6 detalle pasos 1–3: [ESTADO.md](ESTADO.md#árbol-cronológico--pasos-1-2-3-lectura).
3. Dastsc detalle paso 3 WS: sección WebSocket en FLUJO Dastsc (mismo repo hermano).
4. Algoritmo: [BRAKE_V2.md](BRAKE_V2.md) ↔ `nexus-agent/src/brake/planBrake.ts`.

---

## Rutas absolutas (desarrollo local)

```text
```
