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
| `tsw_ue4ss_reader.py` | Parser + monitor + benchmark probe |
| `tsw_telemetry_source.py` | Fuente unificada `ue4ss` / `tsw_api`; filtro HUD |
| `hud_timetable.py` | Lectura `tsw_hud.db`, `car_stop_signs` |
| `driver_aid_parser.py` | DriverAid → planning, estaciones |
| `tsw_ipc_bus.py` | Mandos `SendCommand.txt` |
| `tsw_command_bus.py` | Mandos HTTP PATCH (fallback) |
| `brake_planner.py` / `brake_command.py` | Plan P1 B1–B3 (Dastsc) |
| `governor_station.py` | FSM paradas |
| `autopilot_core.py` / `autopilot_gui.py` | Bucle ~20 Hz + GUI |
| `archive/railbridge/` | Companion SSE — **no usar** |

---

## Lectura vs escritura

| | UE4SS probe | HTTPAPI |
| --- | --- | --- |
| Velocidad, mandos, acel | ✅ ~20 Hz | ✅ ~12 Hz |
| Gradiente vía | `GetDriverAidData` probe | `DriverAid.Data.gradient` |
| 2 límites adelante | ✅ `GetData.txt` | ✅ `DriverAid.Data` |
| Estaciones / horario | No | ✅ `TrackData` + `tsw_hud.db` |
| `PlayerInfo.geoLocation` | No | ✅ match horario HUD |
| Escribir mandos | ✅ `SendCommand.txt` | ✅ PATCH (fallback) |

**Calibración** (`aprender.bat`): solo lectura → UE4SS basta.
**Autopiloto mandos:** IPC (sin `-HTTPAPI`).
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
| `command_bus.py` | `brake_command.py` + allowlist IPC/HTTP |

Mandos permitidos: `PowerBrakeHandle`, `AutomaticBrake`, `IndependentBrake`, `DynamicBrake`.

---

## Roadmap UE4SS

| Fase | Estado | Entregable |
| --- | --- | --- |
| Probe lectura (A3/B1/B2) | ✅ | `TelemetryProbeMod`, `tsw_ue4ss_reader` |
| Integración Python (B3) | ✅ | `tsw_telemetry_source`, aprender/autopilot |
| Gradiente (Lua probe) | ✅ | `gradient_pct` en GetData.txt |
| Escritura Lua (B4) | ✅ | `SendCommand.txt` |
| Planning 2 límites probe | ✅ | `dist_limit_*` en GetData.txt |
| Horario HUD (`tsw_hud.db`) | ✅ planning | `hud_timetable.py` |
| Parada exacta tablón (frenado) | 🔄 | `planBrakeForStation` |
| Freight SD40-2 probe | ⬜ | 4 mandos en `GetData.txt` |

Checklist: [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md).

---

## Preguntas abiertas

1. ~~Formato IPC lectura~~ → TSV en `GetData.txt` ✅
2. ~~Gradiente en probe~~ ✅
3. ~~Planning estaciones sin RailBridge~~ → HUD DB + HTTP ✅
4. ~~B4 SendCommand~~ ✅
5. Distancia tablón en tiempo real (GPS cada tick) vs odometría — pendiente
6. `planBrakeForStation` — prioridad para parada exacta

---

## Notas de sesión

| Fecha | Nota |
| --- | --- |
| 2026-08-18 | Probe 323 ~17 Hz; DynamicHUD `enabled.txt` anulaba `mods.txt` |
| 2026-08-19 | IPC mandos; planning 2 límites |
| 2026-08-22 | Velocidad congelada ~20 Hz GUI |
| 2026-08-23 | HUD timetable: filtro paradas, `car_stop_signs`, merge `hud_geo` |
