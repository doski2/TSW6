# Documentación TSW6 Autopilot

Índice único del proyecto. Todo lo demás está aquí o en `archive/`.

## Empezar

| Documento                                          | Para quién                | Contenido                             |
| -------------------------------------------------- | ------------------------- | ------------------------------------- |
| [GUIA.md](GUIA.md)                                 | Uso diario                | `.bat`, calibración, autopiloto       |
| [ARQUITECTURA.md](ARQUITECTURA.md)                 | Desarrollo                | API TSW, módulos, UE4SS, latencia     |
| [FREIGHT_NA.md](FREIGHT_NA.md)                     | SD40-2 / diesel NA        | Layout multi-mando, fases 4–6         |
| [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md) | UE4SS / telemetría rápida | Investigar + ejecutar TelemetryBridge |
| [NOTAS.txt](NOTAS.txt)                             | Personal                  | Recordatorios de pruebas              |

## Código activo (mapa rápido)

| Módulo                    | Rol                                   |
| ------------------------- | ------------------------------------- |
| `tsw_telemetry_source.py` | Telemetría (UE4SS + HTTPAPI fallback) |
| `tsw_ue4ss_reader.py`     | Parser `GetData.txt` probe            |
| `tsw_ipc_bus.py`          | Mandos vía SendCommand.txt (UE4SS)    |
| `tsw_command_bus.py`      | Mandos HTTPAPI (fallback)             |
| `autopilot_core.py`       | Bucle de control 10 Hz                |
| `autopilot_gui.py`        | Interfaz gráfica del autopilot        |
| `tsw_api_client.py`       | Cliente HTTP bajo nivel               |
| `tsw_monitor.py`          | Monitor consola                       |
| `learn_monitor.py`        | Calibración guiada                    |
| `tsw_autopilot.py`        | Entrada CLI/GUI (`--console`)         |
| `speed_decider.py`        | Decisiones velocidad/freno            |
| `handle_controller.py`    | Ejecución mandos                      |
| `freight_learner.py`      | Perfiles multi-eje NA                 |

## Archivos históricos

| Ruta                                          | Qué es                                  |
| --------------------------------------------- | --------------------------------------- |
| [archive/docs/](../archive/docs/)             | Documentos sustituidos por esta carpeta |
| [archive/railbridge/](../archive/railbridge/) | Código companion RailBridge             |

## Comentar / decidir

Anotaciones de sesión en juego → sección final de [ARQUITECTURA.md](ARQUITECTURA.md).
