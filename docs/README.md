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
| [BRAKE_V2.md](BRAKE_V2.md) | Frenado activo | Arquitectura P1 v2, módulos, prioridad |
| [FREIGHT_NA.md](FREIGHT_NA.md) | SD40-2 / diesel NA | Layout multi-mando, fases 4–6 |
| [ESTADO.md](ESTADO.md) | Tablero visual (Mermaid) qué está hecho y qué sigue |
| [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md) | UE4SS / probe / foco de trabajo |
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
| `braking/v2/` | **Frenado P1** — physics, command, planner, coordinator |
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
