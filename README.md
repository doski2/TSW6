# TSW6 Autopilot

Control automático de velocidad y calibración de perfiles para Train Sim World 6.

**Requisitos:** TSW6 + **UE4SS** (`TelemetryProbeMod`) para telemetría rápida; **`-HTTPAPI`** para
planning de estaciones/horario HUD y escritura HTTP de mandos (opcional si usas IPC).

Python 3.9+ (3.11 recomendado), en cabina.

## Inicio rápido

```bat
iniciar_autopilot.bat
aprender.bat
```

Horarios comerciales (opcional): [docs/HUD_TIMETABLE.md](docs/HUD_TIMETABLE.md) →
`preparar_db_hud.bat`.

## Estructura del proyecto

```
TSW6/
├── tsw6/                 # Código Python (paquete principal)
│   ├── autopilot/        # GUI, core, speed_decider, mandos
│   ├── braking/          # Frenado advisory + Dastsc B1–B3
│   ├── governor/         # FSM estaciones + física
│   ├── telemetry/        # UE4SS, HTTPAPI, DriverAid
│   ├── hud/              # tsw_hud.db / horarios
│   ├── learning/         # Calibración y perfiles
│   └── ui/               # Dashboard consola
├── tests/                # pytest
├── scripts/
│   ├── hud/              # Extracción y preparación tsw_hud.db
│   ├── ue4ss/            # Probe e instalación del mod
│   └── tools/            # Utilidades (verificar_hud_db, etc.)
├── data/                 # timetable.json (fallback manual)
├── docs/                 # Documentación
├── mods/                 # TelemetryProbeMod (UE4SS)
├── archive/              # RailBridge y docs antiguos
├── logs/                 # Perfiles, esquemas, logs (local, gitignored)
├── tsw_autopilot.py      # Entry point autopilot
├── learn_monitor.py      # Entry point calibración
└── tsw_monitor.py        # Entry point monitor HTTPAPI
```

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
