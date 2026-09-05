# Documentación producto v2

Plan maestro del autopilot TSW6 v2 (paquete tren, probe I/O, producto Python `V2/tsw6v2/`).

## Documentos canónicos

| Documento | Rol | Audiencia |
| --- | --- | --- |
| [PLAN_V2.md](PLAN_V2.md) | **Qué / por qué / cuándo** — fases 0–6, orden, deltas, debates | Producto, arquitectura |
| [CODIGO_V2.md](CODIGO_V2.md) | **Dónde va el código nuevo** — carpetas, convenciones, checklist PR | Quien implementa |
| [MANTENIMIENTO.md](MANTENIMIENTO.md) | **Tests, depuración, cierre de paso** — comandos, síntomas, lab vs probe | Cada entrega / sesión |
| [REGLAS_FRENOS_P1.md](REGLAS_FRENOS_P1.md) | **Inventario reglas cartel** — qué hay hoy, debate, refactor sin v1 | Antes de tocar `limit_*` |
| [PLAN_API_EXPLORER.md](PLAN_API_EXPLORER.md) | **Laboratorio Lua** — mod `ApiExplorerMod` (HTTP ↔ UE) | Capturas in-game |
| [LAB_CAPTURA_F5.md](LAB_CAPTURA_F5.md) | Protocolo F5 — HUD, frenar/acelerar, vs GetData | Lab cabina |
| [LAB_CAPTURA_AMPS.md](LAB_CAPTURA_AMPS.md) | Protocolo amperímetro (L0.6f) | Lab EMU/diesel |
| [PROBE_LUA.md](PROBE_LUA.md) | Auditoría probe modular v2 | Probe producción |
| [BAT.md](BAT.md) | Mapa `.bat` raíz → scripts → Python/juego | Operación |

**Backlog de producto:** solo [PLAN_V2.md](PLAN_V2.md). `docs/v1/` = runtime actual (referencia).

## Por dónde empezar

| Objetivo | Lee primero |
| --- | --- |
| Qué hacer y en qué orden | [PLAN_V2 § Orden](PLAN_V2.md#orden-de-implementación) |
| Añadir código o abrir PR | [CODIGO_V2.md](CODIGO_V2.md) |
| pytest, probe, IPC, sesión juego | [MANTENIMIENTO.md](MANTENIMIENTO.md) |
| Captura lab Class 323 (cerrada) | [PLAN_API_EXPLORER § Cierre 323](PLAN_API_EXPLORER.md#cierre-class-323--siguiente-tren) |
| Contrato GetData / IPC | [CANAL_CONTROL.md](../CANAL_CONTROL.md) |

Política v1 vs v2 (no migrar todo, no reescribir desde cero): [PLAN_V2 § Política de
documentación](PLAN_V2.md#política-de-documentación).

## Relacionados (fuera de `v2/`)

| Documento | Contenido |
| --- | --- |
| [CANAL_CONTROL.md](../CANAL_CONTROL.md) | Contrato IPC / GetData (D2) |
| [PENDIENTE_DYNAMICHUD.md](../v1/PENDIENTE_DYNAMICHUD.md) | Probe Lua — bitácora (no backlog) |
| [FREIGHT_NA.md](../v1/FREIGHT_NA.md) | SD40 / fase 6 |
| [assets/esqueleto_v2.svg](../assets/esqueleto_v2.svg) | Árbol v2 |

Índice general: [docs/README.md](../README.md).
