# Arquitectura y roadmap

Estado: **sin RailBridge**. Lectura preferente **UE4SS** (~17 Hz); escritura de mandos vía
**HTTPAPI** (hasta implementar `SendCommand.txt` en Lua).

---

## Stack actual

```text
```

| Módulo | Rol |
| --- | --- |
| `mods/TelemetryProbeMod/` | Mod Lua — lectura HUD, IPC `GetData.txt` |
| `tsw_ue4ss_reader.py` | Parser + monitor + benchmark probe |
| `tsw_telemetry_source.py` | Fuente unificada `ue4ss` / `tsw_api` |
| `tsw_fast_telemetry.py` | Lectura HUD HTTP (~12 Hz máx) |
| `tsw_api_client.py` | Cliente HTTP (auth, GET/PATCH) |
| `tsw_command_bus.py` | Allowlist + dispatch frenos/handle |
| `handle_controller.py` | Un paso de mando por ciclo |
| `tsw_monitor.py` | Dashboard HTTP (depuración) |
| `archive/railbridge/` | Companion SSE — **no usar** |

---

## Lectura vs escritura

| | UE4SS probe | HTTPAPI |
| --- | --- | --- |
| Velocidad, mandos, acel | ✅ ~17 Hz | ✅ ~12 Hz |
| Gradiente vía | `GetDriverAidData` probe | `DriverAid.Data.gradient` |
| Planning / estaciones | No | Parcial `DriverAid` |
| Escribir mandos | ⬜ futuro `SendCommand.txt` | ✅ PATCH hoy |

**Calibración** (`aprender.bat`): solo lectura → UE4SS basta.
**Autopiloto**: lectura UE4SS + escritura HTTP → necesita `-HTTPAPI` hasta fase B4.

---

## API TSW (HTTPAPI)

- URL: `http://localhost:31270`
- Auth: `DTGCommKey` + `X-API-Key`; clave en `Documents\My

  Games\TrainSimWorld6\Saved\Config\CommAPIKey.txt`

- Arranque: `-HTTPAPI` en Steam

| Método | Uso |
| --- | --- |
| `GET /info` | Meta, versión |
| `GET /get/{ruta}` | Nodo (ej. `DriverAid.Data`, `CurrentDrivableActor.Function.HUD_GetSpeed`) |
| `PATCH /set/{ruta}.Value?Value={n}` | Escribir mando |
| `GET /list/{nodo}` | Descubrir rutas |

### Gradiente (HTTPAPI)

```http
```

Alternativa: `CurrentDrivableActor/Simulation/Axle_1_1.TrackGradient_DEG`.

Referencia endpoints: `Desktop\investigacion tsw
6\tsw_projects-main\...\endpoints\DriverAid_endpoints.json`.

### Latencia HTTP (Class 323)

| Operación | ~Tiempo |
| --- | --- |
| GET en ráfaga (sesión caliente) | 15 ms |
| 4 lecturas HUD | 80 ms → ~12 Hz |
| PATCH freno | 50–150 ms |
| Ciclo leer → decidir → mandar | 180–300 ms (3–5 Hz) |

Por eso la **lectura** migró a UE4SS; la **escritura** sigue en HTTP por ahora.

---

## Command bus (patrón Dastsc)

| Dastsc (TSC) | TSW6 hoy | TSW6 objetivo |
| --- | --- | --- |
| `GetData.txt` | ✅ TelemetryProbeMod | ✅ |
| `SendCommand.txt` | ⬜ | Mod Lua + allowlist |
| `command_bus.py` | `tsw_command_bus.py` → PATCH | mismo allowlist, distinto transporte |

Mandos permitidos: `PowerBrakeHandle`, `AutomaticBrake`, `IndependentBrake`, `DynamicBrake`.
Bloqueados: emergencia, reverser, master key, throttle libre.

---

## Roadmap UE4SS

| Fase | Estado | Entregable |
| --- | --- | --- |
| Probe lectura (A3/B1/B2) | ✅ | `TelemetryProbeMod`, `tsw_ue4ss_reader` |
| Integración Python (B3) | ✅ | `tsw_telemetry_source`, aprender/autopilot |
| Gradiente (Lua probe) | ✅ | `gradient_pct` en GetData.txt |
| Escritura Lua (B4) | ⬜ | `SendCommand.txt`, sin `-HTTPAPI` |
| Freight SD40-2 probe | ⬜ | 4 mandos en `GetData.txt` |
| Freight F4–6 | ⬜ | [FREIGHT_NA.md](FREIGHT_NA.md) |

Checklist detallado: [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md).

---

## V2 API — seguimiento código

| Fase | Descripción | Estado |
| --- | --- | --- |
| V2.0 | `tsw_api_client.py` | ✅ |
| V2.1 | `tsw_command_bus.py` | ✅ |
| V2.4 | Autopiloto + `handle_controller` | ✅ (escritura HTTP) |
| V2.5–6 | Freight multi-mando | ⬜ |

---

## Preguntas abiertas

1. ~~Formato IPC lectura~~ → TSV en `GetData.txt` ✅
2. Gradiente: ¿`GetDriverAidData.Gradient` en Lua o poll `DriverAid.Data`?
3. ¿Planning imprescindible en v1 autopiloto? (probablemente no para 323 por límite actual)
4. B4 `SendCommand.txt` — prioridad para quitar `-HTTPAPI`

---

## Notas de sesión

| Fecha | Nota |
| --- | --- |
| 2026-08-18 | Probe 323 ~17 Hz; DynamicHUD `enabled.txt` anulaba `mods.txt` |
| 2026-08-18 | Arquitectura híbrida: UE4SS lee, HTTP escribe |
