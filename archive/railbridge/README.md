# Archivo — integración RailBridge (deprecada)

**Fecha de archivo:** 2026-06-13  
**Motivo:** el proyecto pasa a telemetría y mandos **sin RailBridge** — ver `docs/ARQUITECTURA.md`.

## Contenido

| Archivo | Qué hacía |
| ------- | --------- |
| `tsw_connection.py` | Cliente SSE al Companion (puerto 51160), parseo `companion_dmi_delta` |
| `control_diag.py` | Diagnóstico de mandos vía stream RailBridge (Fase 0 freight) |
| `diag_controles.bat` | Lanzador del diagnóstico RailBridge |
| `test_freight_controls.py` | Tests de parseo del formato companion |
| `test_telemetry_layout.py` | Tests de `get_telemetry()` del companion |

## Sustituto activo

| Antes (RailBridge) | Ahora |
| ------------------ | ----- |
| `tsw_connection.TswConnection` | `tsw_telemetry_source.TswTelemetrySource` |
| SSE companion | API HTTP TSW (`-HTTPAPI`) + futuro mod UE4SS |
| `set_control_value` RPC companion | `tsw_command_bus.dispatch_*` |
| `control_diag.py` | `tsw_monitor.py` / `control_diag_tsw.py` (pendiente) |

## Nota sobre esquemas JSON

Los ficheros `logs/control_schemas/freight_na_railbridge_v3.json` **no** están aquí:
el nombre es histórico; el esquema describe campos API TSW, no depende del companion.

## Restaurar (solo si hace falta)

```powershell
copy archive\railbridge\tsw_connection.py .
```

No recomendado salvo comparación o depuración.
