# Player — catálogo HTTPAPI

Referencia del árbol `Root/Player` en la HTTPAPI de TSW6.

**Dump:**
`Desktop\investigacion tsw 6\apis\tsw-api-export-Player-20260818T172102Z.json` · 2026-08-18 UTC

Árbol pequeño (**6 nodos**, ~181 endpoints). Útil como **puente** entre jugador y DriverAid.

---

## Campos relevantes

| Campo / función | Estado | Qué es | Uso TSW6 |
| --- | --- | --- | --- |
| `Function.GetDriverAidData` | ✅ | Mismo blob que `DriverAid.Data` | Lua probe usa vía controller |
| `Function.IsDrivableActorSpeeding` | 🟡 | ¿Exceso en segmento? | Scoring / debug |
| `Property.SpeedingTolerance` | 🟡 | ~1.34 m/s (~3 mph) | Margen speeding juego |
| `Property.IsSpeedingInSegment` | 🟡 | bool | — |
| `TransformComponent0.Property.RelativeLocation` | ❌ | Posición UE | Debug mapa |
| `DriverInputComponent_*` | ❌ | Componente input jugador | Bajo nivel |

**Nota:** `GetDriverAidData` en Player confirma que **no hace falta** poll HTTP separado si el
probe Lua ya llama al controller en cabina. HTTP sirve para **validar** probe vs juego.

---

## Referencias

- [DRIVERAID_API.md](DRIVERAID_API.md) — desglose del struct DriverAid
- [TSW_HTTPAPI_INDEX.md](TSW_HTTPAPI_INDEX.md)

#### Última revisión: 2026-08-26
