# DriverInput — catálogo HTTPAPI / mandos de cabina

Referencia del árbol `Root/DriverInput` en la HTTPAPI de TSW6 (`-HTTPAPI`, puerto `31270`).

**Dump de origen:**
`Desktop\investigacion tsw 6\apis\tsw-api-export-DriverInput-20260818T171848Z.json`

- Fecha: 2026-08-18 UTC · Class 323 · Lichfield City
- Controles en dump: **88** objetos con endpoints **escribibles**
- Endpoints totales: ~5280 (propiedades + funciones por control)

**Importante:** aquí se **escriben** mandos (`PATCH /set/DriverInput.<Control>.InputValue`). En
producción TSW6 prefiere **IPC** `SendCommand.txt` (menor latencia). HTTPAPI es fallback
(`tsw_command_bus.py`).

---

## Cómo leer este documento

| Estado | Significado |
| --- | --- |
| ✅ En uso | Autopilot / IPC equivalente |
| 🟡 Disponible | En dump; no cableado en Python |
| ❌ No autopiloto | Puertas, MCB, auxiliares |

**Escritura HTTP:**

```http
```

`InputValue` suele ser **normalizado** (−1…+1 o 0…1 según control), no muesca entera 0–8.

---

## Mandos de tracción / freno (Class 323)

| Control | `InputValue` dump | Estado | Equivalente probe / IPC |
| --- | --- | --- | --- |
| `PowerBrakeHandle` | −0.20 | ✅ | `power` / `handle_notch` — **mando combinado UK** |
| `Reverser` | ~0.667 | ✅ | Marcha (F/N/R) |
| `EmergencyBrake_L` / `_C` | 0 | 🟡 | Freno emergencia cabina |
| `ParkingBrake` | 0 | 🟡 | Freno estacionamiento |
| `RegenBrakes` | 1 | 🟡 | Regenerativo on |
| `Sander` | 0 | 🟡 | Arena manual |
| `MasterKey` | 1 | 🟡 | Contacto |

### Debate: ¿calibrar muescas vía `NumberOfNotches`?

Cada palanca expone propiedades de diseño:

- `MinimumInputValue` / `MaximumInputValue`
- `MinimumOutputValue` / `MaximumOutputValue`
- `NumberOfNotches`
- `GetCurrentNotchIndex` (función)

**Propuesta:** script de calibración que lea `PowerBrakeHandle.Property.NumberOfNotches` y
mapee `InputValue` ↔ muesca 0–8 sin tabla fija por tren.

---

## Seguridad y auxiliares (no autopiloto)

| Grupo | Ejemplos | Estado |
| --- | --- | --- |
| Puertas | `DoorControlPanel_*`, `CabDoor_*` | ❌ FSM estación usa telemetría puertas |
| MCB | `MCB_TrainBrake`, `MCB_Sand`, `MCB_LocalDoors*` | ❌ |
| Pantógrafo | `PantographRaise` / `Lower` | ❌ |
| Luces / bocina | `HeadlightsMarkerLights`, `Horn` | ❌ |
| Limpiaparabrisas | `WiperControl`, `WiperBladesSet` | ❌ |

---

## Relación con CurrentFormation

| Lectura (HUD) | Escritura (DriverInput) |
| --- | --- |
| `HUD_GetPowerHandle` | `PowerBrakeHandle.InputValue` |
| `HUD_GetTrainBrakeHandle` | (mismo eje en UK combined) |
| `HUD_GetAcceleration` | — (solo lectura) |

La simulación interna (`Simulation_BrakeInput_InputValue`) refleja el mando **después** de la
palanca; no sustituye escribir `DriverInput`.

---

## Referencias

| Archivo | Relación |
| --- | --- |
| [CURRENTFORMATION_API.md](CURRENTFORMATION_API.md) | Lectura HUD / física |
| [TSW_HTTPAPI_INDEX.md](TSW_HTTPAPI_INDEX.md) | Índice |
| `tsw6/telemetry/tsw_ipc_bus.py` | Mandos preferidos |
| `tsw6/telemetry/tsw_command_bus.py` | PATCH HTTP fallback |

#### Última revisión: 2026-08-26
