# Documentación TSW6 Autopilot

Índice único del proyecto. Todo lo demás está aquí o en `archive/`.

## Empezar

| Documento | Para quién | Contenido |
| --- | --- | --- |
| [GUIA.md](GUIA.md) | Uso diario | `.bat`, calibración, autopilot, HUD horarios |
| [HUD_TIMETABLE.md](HUD_TIMETABLE.md) | Servicios UK / paradas | `tsw_hud.db`, extractor, planning comercial |
| [ARQUITECTURA.md](ARQUITECTURA.md) | Desarrollo | API TSW, módulos, UE4SS, latencia |
| [DRIVERAID_API.md](DRIVERAID_API.md) | HTTPAPI / DriverAid | Catálogo nodos, estaciones, geo |
| [DASTSC_PARITY.md](DASTSC_PARITY.md) | Frenado P1 | Paridad con Dastsc, B1–B3, pendientes |
| [FREIGHT_NA.md](FREIGHT_NA.md) | SD40-2 / diesel NA | Layout multi-mando, fases 4–6 |
| [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md) | UE4SS / telemetría | Probe, IPC, planning híbrido |
| [NOTAS.txt](NOTAS.txt) | Personal | Recordatorios de pruebas |

## Código activo (mapa rápido)

| Módulo | Rol |
| --- | --- |
| `tsw_telemetry_source.py` | Telemetría UE4SS + HTTPAPI; filtro estaciones HUD |
| `hud_timetable.py` | Lectura `tsw_hud.db`, `car_stop_signs`, merge paradas |
| `tsw_ue4ss_reader.py` | Parser `GetData.txt` probe |
| `tsw_ipc_bus.py` | Mandos vía `SendCommand.txt` (UE4SS) |
| `tsw_command_bus.py` | Mandos HTTPAPI (fallback) |
| `driver_aid_parser.py` | `DriverAid` → planning, estaciones, límites |
| `autopilot_core.py` | Bucle de control ~20 Hz |
| `autopilot_gui.py` | GUI tkinter (Estado / Planning / Depuración) |
| `speed_decider.py` | Decisiones velocidad/freno + FSM estación |
| `brake_planner.py` | Plan límite B1–B3 (Dastsc) |
| `brake_command.py` | Comando notch directo P1 |
| `brake_release.py` | RELEASE al objetivo, anti-rebrake |
| `governor_station.py` | FSM paradas (APPROACHING / STOPPED / DEPARTING) |
| `handle_controller.py` | Ejecución mandos |
| `distance_format.py` | Distancias uk_imperial / metric en GUI |
| `learn_monitor.py` | Calibración guiada |
| `tsw_autopilot.py` | Entrada CLI/GUI (`--console`) |

## Desarrollo

| Recurso | Uso |
| --- | --- |
| `requirements-dev.txt` | `pytest` y dependencias de test |
| `.venv/` | Entorno virtual recomendado (pyright + tests) |
| `pyrightconfig.json` | Analizador de tipos (basedpyright) |

```bat
```

## Archivos históricos

| Ruta | Qué es |
| --- | --- |
| [archive/docs/](../archive/docs/) | Documentos sustituidos por esta carpeta |
| [archive/railbridge/](../archive/railbridge/) | Código companion RailBridge |

## Comentar / decidir

Anotaciones de sesión en juego → sección final de [ARQUITECTURA.md](ARQUITECTURA.md).
