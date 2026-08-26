# TimeOfDay — catálogo HTTPAPI

Referencia del árbol `Root/TimeOfDay` en la HTTPAPI de TSW6.

**Dump:**
`Desktop\investigacion tsw 6\apis\tsw-api-export-TimeOfDay-20260818T172049Z.json` · 2026-08-18 UTC

Un solo endpoint: `TimeOfDay.Data`.

---

## `TimeOfDay.Data`

| Campo | Ejemplo dump | Estado | Uso |
| --- | --- | --- | --- |
| `WorldTimeISO8601` | `2019-08-18T08:14:34.571Z` | 🟡 | Hora **del escenario** (no reloj real) |
| `LocalTimeISO8601` | idem + offset | 🟡 | Hora local escenario |
| `SystemTimeISO8601` | `2026-08-18T17:20:49Z` | ❌ | Reloj sistema PC |
| `DayPercentage` | ~0.23 | 🟡 | Progreso día (0–1) |
| `SunriseTime` / `SunsetTime` | strings | ❌ | Iluminación |
| `OriginLatitude` / `OriginLongitude` | ~51.52, −0.68 | 🟡 | Coherente con DriverAid geo |

### Relación con horario autopilot

TSW6 usa **`tsw_hud.db`** + `PlayerInfo.currentServiceName` + `geoLocation` para ETA de
estación (`schedule_slack`, holgura). `TimeOfDay` podría:

- Validar desfase reloj escenario vs tabla HUD.
- Detectar cambio de día en sesiones largas.

**No integrado** hoy — prioridad baja frente a `DriverAid.PlayerInfo` + HUD DB.

---

## Referencias

- [HUD_TIMETABLE.md](HUD_TIMETABLE.md)
- [DRIVERAID_API.md](DRIVERAID_API.md) § PlayerInfo
- [TSW_HTTPAPI_INDEX.md](TSW_HTTPAPI_INDEX.md)

#### Última revisión: 2026-08-26
