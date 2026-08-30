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

ETA de estación sale de **`tsw_hud.db`** + `PlayerInfo.currentServiceName` + `geoLocation`.
La holgura P1 (`schedule_slack`) **no** usa este árbol hoy: usa el reloj del PC.

`TimeOfDay` es el reloj del **escenario**. Siguiente uso (ver
[PENDIENTE_DYNAMICHUD.md](../v1/PENDIENTE_DYNAMICHUD.md) § Horario):

- `now` de `station_plan.schedule_slack_sec` (`WorldTimeISO8601` o `LocalTimeISO8601`).
- Desfase visible en Planning (`ETA` vs hora de llegada).
- Cambio de día en sesiones largas.

Poll HTTP lento (como gradiente fallback), no el bucle 17 Hz.

**No integrado** — bloquea holgura usable; no bloquea Planning (llegada/salida).

#### Última revisión: 2026-08-28
