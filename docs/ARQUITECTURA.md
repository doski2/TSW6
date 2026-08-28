# Arquitectura y roadmap

Estado: **sin RailBridge**. Lectura preferente **UE4SS** (~20 Hz); escritura de mandos vía
**IPC** (`SendCommand.txt`); planning estaciones vía **HTTPAPI** + **`tsw_hud.db`**.

---

## Stack actual

```text
```

| Módulo | Rol |
| --- | --- |
| `mods/TelemetryProbeMod/` | Mod Lua — lectura HUD, IPC |
| `tsw6/telemetry/tsw_ue4ss_reader.py` | Parser + monitor + benchmark probe |
| `tsw6/telemetry/tsw_telemetry_source.py` | Fuente unificada `ue4ss` / `tsw_api`; filtro HUD |
| `tsw6/hud/hud_timetable.py` | Lectura `tsw_hud.db`, `car_stop_signs` |
| `tsw6/telemetry/driver_aid_parser.py` | DriverAid → planning, estaciones |
| `tsw6/telemetry/tsw_ipc_bus.py` | Mandos `SendCommand.txt` |
| `tsw6/telemetry/tsw_command_bus.py` | Mandos HTTP PATCH (fallback) |
| `tsw6/autopilot/train_state.py` | Instantánea inmutable por ciclo |
| `tsw6/autopilot/speed_decider.py` | FSM → P1 v2 → HOLD |
| `tsw6/autopilot/handle_controller.py` | Ejecución notch + SafetyWatchdog |
| `tsw6/governor/governor_physics.py` | Física tren, learner, distancias |
| `tsw6/governor/governor_station.py` | FSM comercial: puertas Lua/DMI, no OCR |
| `tsw6/braking/v2/` | **Frenado P1** — coordinator, policy, objectives, station_plan, limit_brake, command |
| `tsw6/autopilot/autopilot_core.py` | Bucle ~20 Hz + GUI |
| `archive/railbridge/` | Companion SSE — **no usar** |

Detalle frenado P1: [BRAKE_V2.md](BRAKE_V2.md). Paridad Dastsc:
[DASTSC_PARITY.md](DASTSC_PARITY.md).

---

## Lectura vs escritura

| | UE4SS probe | HTTPAPI |
| --- | --- | --- |
| Velocidad, mandos, acel | ✅ ~20 Hz | ✅ ~12 Hz |
| Gradiente vía | `GetDriverAidData` probe | `DriverAid.Data.gradient` |
| 1 próximo límite | ✅ `GetData.txt` (escalares) | ✅ `DriverAid.Data` (cola JSON; no en probe) |
| Estaciones / horario | No | ✅ `TrackData` + `tsw_hud.db` |
| `PlayerInfo.geoLocation` | No | ✅ match horario HUD |
| Escribir mandos | ✅ `SendCommand.txt` → Lua UE4SS (sin HTTP) | ✅ PATCH (fallback Python) |

**Calibración** (`aprender.bat`): solo lectura → UE4SS basta.
**Autopiloto mandos:** IPC → Lua UE4SS (canal principal). HTTP PATCH solo fallback en Python
(`tsw_command_bus.py`); el mod Lua **nunca** usa HTTP — ver [CANAL_CONTROL.md](CANAL_CONTROL.md#lua-probe--http-api).
**Autopiloto paradas HUD:** `-HTTPAPI` + `tsw_hud.db`.

---

## Planning estaciones (HUD)

```text
```

Hilo `tsw-planning`: poll HTTP async; SQLite thread-local en `HudTimetableStore`.

Detalle: [HUD_TIMETABLE.md](HUD_TIMETABLE.md).

---

## API TSW (HTTPAPI)

- URL: `http://localhost:31270`
- Auth: `DTGCommKey` + `X-API-Key`; clave en `Documents\My

  Games\TrainSimWorld6\Saved\Config\CommAPIKey.txt`

- Arranque: `-HTTPAPI` en Steam

| Método | Uso |
| --- | --- |
| `GET /info` | Meta, versión |
| `GET /get/{ruta}` | Nodo (ej. `DriverAid.Data`, `DriverAid.PlayerInfo`) |
| `PATCH /set/{ruta}.Value?Value={n}` | Escribir mando |
| `GET /list/{nodo}` | Descubrir rutas |

Catálogos por árbol (`DriverAid`, `CurrentFormation`, `DriverInput`, …):
[TSW_HTTPAPI_INDEX.md](TSW_HTTPAPI_INDEX.md). Física del tren (masa, aire, esfuerzos):
[CURRENTFORMATION_API.md](CURRENTFORMATION_API.md).

Catálogo DriverAid: [DRIVERAID_API.md](DRIVERAID_API.md).

### Latencia HTTP (Class 323)

| Operación | ~Tiempo |
| --- | --- |
| GET en ráfaga (sesión caliente) | 15 ms |
| Poll planning (Data + TrackData + PlayerInfo) | ~2 s intervalo |
| PATCH freno | 50–150 ms |

Lectura crítica (velocidad) en UE4SS; HTTP para planning lento.

---

## Command bus (patrón Dastsc)

| Dastsc (TSC) | TSW6 |
| --- | --- |
| `GetData.txt` | ✅ TelemetryProbeMod |
| `SendCommand.txt` | ✅ `tsw_ipc_bus.py` |
| `command_bus.py` | `v2/command.py` + `BrakeCoordinatorV2` + allowlist IPC/HTTP |

Mandos permitidos: `PowerBrakeHandle`, `AutomaticBrake`, `IndependentBrake`, `DynamicBrake`.

**Lua probe:** resolución de mandos por UObject en cabina (`main.lua`); Class 323 escribe
`PowerBrakeHandle.InputValue` en eje -1..1. Detalle canal IPC y separación HTTP:
[CANAL_CONTROL.md](CANAL_CONTROL.md#lua-probe--http-api).

---

## Roadmap UE4SS

| Fase | Estado | Entregable |
| --- | --- | --- |
| Probe lectura (A3/B1/B2) | ✅ | `TelemetryProbeMod`, `tsw_ue4ss_reader` |
| Integración Python (B3) | ✅ | `tsw_telemetry_source`, aprender/autopilot |
| Gradiente (Lua probe) | ✅ | `gradient_pct` en GetData.txt |
| Escritura Lua (B4) | ✅ | `SendCommand.txt` |
| Planning 1 límite probe | ✅ | `dist_limit_cm` / `next_limit_ms` |
| 2.º límite (`lim2`) | ⬜ | [DRIVERAID_API.md](DRIVERAID_API.md#investigar-2º-límite-lim2) |
| Horario HUD (`tsw_hud.db`) | ✅ planning + GUI arr/dep | `hud_timetable.py` |
| Frenado P1 v2 (autopilot) | ✅ | `braking/v2/` — ver [BRAKE_V2.md](BRAKE_V2.md) |
| Parada andén (`plan_brake_for_station`) | ✅ | `v2/objectives` → `v2/station_plan.py` |
| Señal rojo (DANGER) | ⬜ | `evaluate_signal_brake` stub; falta telemetría |
| Freight SD40-2 probe | ⬜ | 4 mandos en `GetData.txt` |
| Canal v2 / rendimiento | ⬜ debate | [CANAL_CONTROL.md § plan](CANAL_CONTROL.md#plan-debate--rendimiento--canal-v2-2026-08-28) |

Checklist: [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md).

---

## Preguntas abiertas

1. ~~Formato IPC lectura~~ → TSV en `GetData.txt` ✅
2. ~~Gradiente en probe~~ ✅
3. ~~Planning estaciones sin RailBridge~~ → HUD DB + HTTP ✅
4. ~~B4 SendCommand~~ ✅
5. Distancia tablón en tiempo real (GPS cada tick) vs odometría — pendiente
6. Telemetría señal DANGER → `evaluate_signal_brake`
7. Canal: **A** (20 Hz estables); **B** SHM solo si el `.txt` limita — [CANAL_CONTROL.md](CANAL_CONTROL.md#plan-debate--rendimiento--canal-v2-2026-08-28)

---

## Notas de sesión

| Fecha | Nota |
| --- | --- |
| 2026-08-18 | Probe 323 ~17 Hz; DynamicHUD `enabled.txt` anulaba `mods.txt` |
| 2026-08-19 | IPC mandos; intento 2 límites (luego 1 escalar) |
| 2026-08-28 | A1 tick: log ciclo, layout cache, handle GetData; hitch carga aceptado |
| 2026-08-22 | Velocidad congelada ~20 Hz GUI |
| 2026-08-23 | HUD timetable: filtro paradas, `car_stop_signs`, merge `hud_geo` |
| 2026-08-24 | P1 v2 en autopilot (`BrakeCoordinatorV2`); todo frenado en `braking/v2/` |
| 2026-08-24 | Consolidación v2 — eliminado `archive/braking_v1/` |
| 2026-08-27 | Lua probe: mandos vía `InputValue` eje (Class 323); documentado Lua ≠ HTTP |
