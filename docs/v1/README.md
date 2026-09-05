# Documentación v1 — runtime actual

Cómo funciona el autopilot **hoy** (`autopilot_core`, probe Class 323, P1 en `braking/v2/`).

**Backlog y producto futuro:** [v2/PLAN_V2.md](../v2/PLAN_V2.md) — única lista de trabajo.

**Política de docs (no duplicar v1→v2):** [PLAN_V2 § Política de
documentación](../v2/PLAN_V2.md#política-de-documentación).

| Documento | Contenido |
| --- | --- |
| [GUIA.md](GUIA.md) | Uso diario — `.bat`, calibración, autopilot |
| [ARQUITECTURA.md](ARQUITECTURA.md) | Módulos, UE4SS, stack lectura/escritura |
| [ESTADO.md](ESTADO.md) | Tablero visual — árbol cronológico 1–14 |
| [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md) | Probe Lua — reglas, log, bitácora |
| [BRAKE_V2.md](BRAKE_V2.md) | P1 activo — coordinator, physics, policy |
| [FLUJO_FRENOS.md](FLUJO_FRENOS.md) | Ciclo P1 paso a paso |
| [FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md) | Learner, distancias, fill-time |
| [HUD_TIMETABLE.md](HUD_TIMETABLE.md) | `tsw_hud.db`, paradas UK |
| [FREIGHT_NA.md](FREIGHT_NA.md) | SD40-2 — layout split (fase 6 v2) |
| [DASTSC_PARITY.md](DASTSC_PARITY.md) | Paridad histórica con Dastsc |
| [COMPARATIVA_DASTSC_FLUJO.md](COMPARATIVA_DASTSC_FLUJO.md) | TSW6 ↔ Nexus V4 (estudio) |

**Compartido:** [CANAL_CONTROL.md](../CANAL_CONTROL.md) (contrato IPC) · [reference/](../reference/)
(HTTP API).

Índice raíz: [docs/README.md](../README.md).
