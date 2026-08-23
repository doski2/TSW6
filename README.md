# TSW6 Autopilot

Control automático de velocidad y calibración de perfiles para Train Sim World 6.

**Requisitos:** TSW6 + **UE4SS** (`TelemetryProbeMod`) para telemetría rápida; **`-HTTPAPI`** para
planning de estaciones/horario HUD y escritura HTTP de mandos (opcional si usas IPC).

Python 3.9+ (3.11 recomendado), en cabina.

## Inicio rápido

```bat
```

Horarios comerciales (opcional): [docs/HUD_TIMETABLE.md](docs/HUD_TIMETABLE.md) →
`preparar_db_hud.bat`.

## Documentación

Todo está en **[docs/README.md](docs/README.md)**:

- [Guía de uso](docs/GUIA.md) — `.bat`, calibración, autopilot
- [Horarios HUD](docs/HUD_TIMETABLE.md) — `tsw_hud.db`, paradas programadas
- [DriverAid API](docs/DRIVERAID_API.md) — nodos HTTPAPI
- [Paridad Dastsc](docs/DASTSC_PARITY.md) — frenado B1–B3
- [Arquitectura](docs/ARQUITECTURA.md) — módulos, UE4SS, latencia
- [Freight NA](docs/FREIGHT_NA.md) — SD40-2, fases pendientes
- [Pendiente DynamicHUD](docs/PENDIENTE_DYNAMICHUD.md) — telemetría probe

Código RailBridge archivado: `archive/railbridge/`
