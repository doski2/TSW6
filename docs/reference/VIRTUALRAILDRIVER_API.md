# VirtualRailDriver — catálogo HTTPAPI

Referencia del árbol `Root/VirtualRailDriver` en la HTTPAPI de TSW6.

**Dump:**
`Desktop\investigacion tsw 6\apis\tsw-api-export-VirtualRailDriver-20260818T172118Z.json` ·
2026-08-18 UTC

Simula un **mando físico genérico** (botones fila superior/inferior, D-pad, freno automático).
En dump Class 323 la mayoría de campos escribibles devuelven `INVALID` — el tren usa
`DriverInput` real.

---

## Endpoints

| Campo | Writable | Estado | Notas |
| --- | --- | --- | --- |
| `Data` | no | ❌ | Snapshot botones (todos 0) |
| `Enabled` | **sí** | ❌ | `false` en dump |
| `Throttle` / `Reverser` | **sí** | ⚠️ | Genérico; no Class 323 |
| `Auto Brake` / `Independent Brake` | **sí** | ⚠️ INVALID | Freight US |
| Filas `Front Top/Bottom Row *` | **sí** | ⚠️ INVALID | Hardware virtual |

**Conclusión:** no usar en autopilot UK. Documentado solo para no confundir con `DriverInput`.

---

## Referencias

- [DRIVERINPUT_API.md](DRIVERINPUT_API.md)
- [TSW_HTTPAPI_INDEX.md](TSW_HTTPAPI_INDEX.md)

#### Última revisión: 2026-08-26
