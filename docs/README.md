# Documentación TSW6 Autopilot

```text
```

## Por dónde empezar

| Objetivo | Documento |
| --- | --- |
| **Qué hacer / en qué orden** | [v2/PLAN_V2.md](v2/PLAN_V2.md) |
| **Añadir código v2 / PR** | [v2/CODIGO_V2.md](v2/CODIGO_V2.md) |
| **Tests y depuración v2** | [v2/MANTENIMIENTO.md](v2/MANTENIMIENTO.md) |
| **Usar el autopilot hoy** | [v1/GUIA.md](v1/GUIA.md) |
| **Entender el código actual** | [v1/ARQUITECTURA.md](v1/ARQUITECTURA.md) · [v1/ESTADO.md](v1/ESTADO.md) |
| **Probe Lua / log** | [v1/PENDIENTE_DYNAMICHUD.md](v1/PENDIENTE_DYNAMICHUD.md) |
| **Contrato GetData / IPC** | [CANAL_CONTROL.md](CANAL_CONTROL.md) |
| **Laboratorio Lua (HTTP ↔ UE)** | [v2/PLAN_API_EXPLORER.md](v2/PLAN_API_EXPLORER.md) |
| **API HTTP del juego** | [reference/](reference) |

**Regla:** backlog solo en [v2/PLAN_V2.md](v2/PLAN_V2.md). `v1/` y `reference/` son referencia, no
listas de tareas.

**Política v1 ↔ v2:** [PLAN_V2 § Política de documentación](v2/PLAN_V2.md#política-de-documentación)
— no migrar `v1/` en bloque; ampliar `v2/` y `reference/` de forma incremental.

**Enlaces antiguos:** si abres `docs/GUIA.md`, `docs/ESTADO.md`, etc. en la raíz, verás un stub
«Movido» que apunta a `v1/` o `reference/`.

---

## v1 — runtime actual

Índice completo: [v1/README.md](v1/README.md).

| Documento | Contenido |
| --- | --- |
| [GUIA.md](v1/GUIA.md) | `.bat`, calibración, autopilot |
| [ARQUITECTURA.md](v1/ARQUITECTURA.md) | Módulos, UE4SS |
| [ESTADO.md](v1/ESTADO.md) | Árbol 1–14, tablero visual |
| [BRAKE_V2.md](v1/BRAKE_V2.md) | P1 frenado |
| [FLUJO_FRENOS.md](v1/FLUJO_FRENOS.md) | Ciclo coordinator |
| [PENDIENTE_DYNAMICHUD.md](v1/PENDIENTE_DYNAMICHUD.md) | Probe, bitácora |

## v2 — producto

Índice: [v2/README.md](v2/README.md).

| Documento | Contenido |
| --- | --- |
| [v2/PLAN_V2.md](v2/PLAN_V2.md) | Plan, fases, orden, deltas |
| [v2/CODIGO_V2.md](v2/CODIGO_V2.md) | Dónde va código nuevo, convenciones PR |
| [v2/MANTENIMIENTO.md](v2/MANTENIMIENTO.md) | Tests, depuración, cierre de paso |
| [v2/PLAN_API_EXPLORER.md](v2/PLAN_API_EXPLORER.md) | Laboratorio Lua |
| [assets/esqueleto_v2.svg](assets/esqueleto_v2.svg) | Árbol producto v2 |

## reference — HTTP API

Índice: [reference/README.md](reference/README.md).

## Código activo (mapa rápido)

| Módulo | Rol |
| --- | --- |
| `mods/TelemetryProbeMod/` | Probe Lua ~20 Hz |
| `mods/ApiExplorerMod/` | Laboratorio Lua (HTTP ↔ UE) |
| `tsw6/braking/v2/` | P1 — coordinator, policy, physics |
| `V2/tsw6v2/` | Producto Python v2 (nuevo) |
| `tsw6/autopilot/autopilot_core.py` | Bucle ~20 Hz hoy (v1) |
| `tsw6/telemetry/` | IPC, parser GetData, HTTP planning |

## Desarrollo

```bat
```

| Recurso | Uso |
| --- | --- |
| `requirements-dev.txt` | pytest, dev deps |
| `.venv/` | Entorno recomendado |

## Histórico

| Ruta | Qué es |
| --- | --- |
| [archive/docs/](../archive/docs/) | Docs sustituidos |
| [archive/railbridge/](../archive/railbridge/) | RailBridge (no usar) |

Decisiones de producto → [v2/PLAN_V2.md](v2/PLAN_V2.md). Notas de sesión →
[v1/ARQUITECTURA.md](v1/ARQUITECTURA.md).
