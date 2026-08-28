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

## Catálogo de nombres: no escanear en el tick Lua

Los **nombres** de palanca no se inventan en `ReceiveTick`. Fuentes, en este orden:

1. **Perfiles tsw-controller-app** (abajo) — nombre UE + rango / peldaños.
2. **HTTP `DriverInput`** — dump de esta página / export JSON.
3. **F9 en el probe** — dump **manual** al `UE4SS.log` si el perfil no existe o no cuadra. No en el bucle ~20 Hz.

`main.lua` en producción: `GetDrivableActor().PowerBrakeHandle` (caché). Python 323: `CLASS323_PBH_INPUT_BY_NOTCH` en `tsw_command_bus.py`.

No instalar el mod de tsw-controller-app a la vez que TelemetryProbe (dos escritores).

### Dónde están los perfiles (otros trenes)

Copia local (investigación; ~140 locos):

`C:\Users\doski\Desktop\investigacion tsw 6\tsw-controller-app-main\shared-profiles\`

Upstream (si la copia se queda vieja):

<https://github.com/LiahMartens/tsw-controller-app/tree/main/shared-profiles>

| Buscas | Archivo típico |
| --- | --- |
| Class 323 / Cross-City | `class323.tswprofile` |
| Otra UK EMU | `class314.tswprofile`, `class170.tswprofile`, … |
| Freight NA | `bnsf_sd40.tswprofile`, `acs64.tswprofile`, … |

Cómo leer un `.tswprofile` (JSON):

- `direct_control` / `api_control` → **`controls`**: nombre UObject (`PowerBrakeHandle`, `Throttle`, `AutomaticBrake`, …).
- `input_value.min` / `max` / `steps` → escala **InputValue**, no la línea IPC `muesca/8`.
- `sync_control` + `keys` → teclado; no es IPC.
- El bloque `"controller"` (USB, ejes) es el joystick de Liah; **ignorarlo** para el autopilot.

Eso no sustituye `GetData.txt` / `SendCommand.txt`. Solo aclara **qué escribir** al añadir un tren.

### Qué más hay en esa repro (no mezclar con el probe)

Raíz local: `C:\Users\doski\Desktop\investigacion tsw 6\tsw-controller-app-main\`

| Carpeta / archivo | ¿Aprovechar? | Para qué |
| --- | --- | --- |
| `shared-profiles/` + `index.json` | **Sí** | Nombres y rangos por loco |
| `PROFILE_EXPLAINER.md` | **Sí** (lectura) | `direct_control`, `{SIDE}`, `max_change_rate`, `steps` |
| `tsw-controller-mod/ue4ss-mod/src/dllmain.cpp` | **Receta**, no el DLL | Escritura nativa: `FindVirtualHIDComponent` → `NotifyBeginInteraction` / `BeginChangingVHIDComponent` → `SetCurrentInputValue` (o `SetNormalisedInputValue` / `SetPushedState`) → `EndUsingVHIDComponent`. `{SIDE}` vía `SeatSide`. Algunos trenes: `CallUpdateFunctions`. Cab debugger: hook `InputValueChanged`. |
| `go-app/` (app, cab debugger, joysticks) | **No** | Otro producto (HID → tren). No telemetría de vía. |
| `socket-connection-lib/` | **No** | Su canal; el nuestro es `%TEMP%\TSW6Bridge\` |
| `PROXY_MODE.md` + `api_control` HTTP | **No** | Palanca por `:31270`; en TSW6 ya descartado |
| `tsc-controller-mod/` | Solo si TSC | Como Dastsc `SetControlValue`; no TSW |
| `virtual-controller/` | **No** | App Android / HID virtual |

Si el 323 deja de responder a `SetCurrentOutputValue`, el probe ya prueba `SetCurrentInputValue` (mismo objeto palanca; `FindVirtualHIDComponent` no hace falta si el hijo existe). No instalar su CppMod junto a TelemetryProbe.

---

## Mandos de tracción / freno (Class 323)

| Control | `InputValue` | Estado | Notas |
| --- | --- | --- | --- |
| `PowerBrakeHandle` | ver peldaños abajo | ✅ IPC | Combinado UK · perfil Liah |
| `Reverser` | ~0.667 | 🟡 | Teclas; no autopilot |
| `EmergencyBrake_L` / `_C` | 0 | 🟡 | Distinto del notch 0 del combinado |
| `ParkingBrake` | 0 | 🟡 | |
| `RegenBrakes` | 1 | 🟡 | |
| `Sander` | 0 | 🟡 | |
| `MasterKey` | 1 | 🟡 | |

### Peldaños `PowerBrakeHandle.InputValue` (Class 323)

IPC sigue siendo **muesca/8** (0…1). Escritura nativa de producción: `SetCurrentOutputValue(muesca−4)`. Si el HUD no se mueve, el probe (`20260828o`) prueba el handshake Liah: `BeginChangingVHIDComponent` + `SetCurrentInputValue` con los peldaños de abajo (no `SetInputValue()`, que crashea). En `UE4SS.log`: `PBH write OK via SetCurrentOutputValue` o `via VHID SetCurrentInputValue`.

| Muesca HUD | InputValue | Significado |
| --- | --- | --- |
| 0 | −1.0 | Emergencia HUD (no está en el perfil Liah; 8 peldaños hardware) |
| 1 | −0.6 | B3 |
| 2 | −0.4 | B2 |
| 3 | −0.2 | B1 |
| 4 | 0 | Neutro |
| 5 | 0.25 | P1 |
| 6 | 0.5 | P2 |
| 7 | 0.75 | P3 |
| 8 | 1.0 | P4 |

Origen: `shared-profiles/class323.tswprofile` (`min` −0.6, `max` 1, `steps` −0.6…1). No calibrar cada tick con `NumberOfNotches`.

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
| `tsw6/telemetry/tsw_command_bus.py` | PATCH HTTP + peldaños Class 323 |

#### Última revisión: 2026-08-28
