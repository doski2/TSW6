# DriverAid — catálogo HTTPAPI / Lua

Referencia de los nodos bajo `Root/DriverAid` en la HTTPAPI de TSW6 (`-HTTPAPI`, puerto
`31270`).

**Dump de origen (sesión real):**
`Desktop\investigacion tsw 6\apis\tsw-api-export-DriverAid-20260818T171822Z.json`

- Fecha captura: 2026-08-18 UTC
- Ruta: Cross-City (Class 323, andén Lichfield)
- Cliente: RailBridge crawler / export `telemetry_subtree`

**Importante:** este árbol describe **vía, límites, señales y planning** — no los mandos de
freno. Para calibrar frenos usa el probe (`train_brake`, `loco_brake`, `dyn_brake`, `power`) o
`CurrentDrivableActor.Function.HUD_Get*`. DriverAid sirve sobre todo para **gradiente**, **límite
actual**y**anticipación** (próximo límite, señal, estación).

**¿Revisar este archivo?** Sí, pero como **catálogo de referencia** (qué existe en TSW), no como
lista de tareas. El tablero de trabajo está en [ESTADO.md](ESTADO.md). Actualiza aquí solo cuando
cambie el **estado de integración** (probe, HTTP, P1) — no hace falta releerlo entero cada sesión.

**Índice de todos los árboles HTTPAPI:** [TSW_HTTPAPI_INDEX.md](TSW_HTTPAPI_INDEX.md) · Física del
tren (masa, aire, esfuerzos): [CURRENTFORMATION_API.md](CURRENTFORMATION_API.md)

### Mapa implementación TSW6 (2026-08-24)

| Campo / nodo | Probe Lua (GetData) | HTTP (`tsw_telemetry_source`) | P1 autopilot |
| --- | --- | --- | --- |
| `speedLimit`, `gradient` | ✅ ~20 Hz | ✅ fallback / validación | ✅ |
| `distanceToNextSpeedLimit`, `nextSpeedLimit` | ✅ 1 límite ~20 Hz (escalares) | Parser HTTP listo; probe no usa HTTP para límites | ✅ `limit_brake` (P1 al 1.er cartel) |
| `nextSpeedLimits[]` (2.º cambio) | ❌ Lua: ítems `UScriptStruct`, `d=nil` | ✅ en JSON HTTP | ⬜ no cablear hasta leer floats |
| `TrackData.markers` | ❌ | ✅ ~2 s | ✅ con `tsw_hud.db` |
| `PlayerInfo` (servicio, geo) | ❌ | ✅ ~2 s | ✅ horario HUD |
| `distanceToSignal`, aspecto | ❌ | 🟡 en API, no cableado | ❌ `evaluate_signal_brake` stub |
| `trackHeights[]`, perfil | ❌ | ❌ | ❌ futuro |

**Estudiar ahora (tarjeta C1):** señales — validar en juego si `signalAspectClass` = `Stop` /
`DANGER` y si conviene probe Lua o HTTP. **No bloquea** entender pasos 1–3 del flujo.

---

## Cómo leer este documento

| Columna | Significado |
| --- | --- |
| **Estado** | Si lo usamos hoy en TSW6 |
| **HTTP** | `GET http://127.0.0.1:31270/get/DriverAid.<nodo>` |
| **Lua** | Equivalente vía `playerController:GetDriverAidData(driverAid)` cuando existe |

Estados habituales:

| Estado | Significado |
| --- | --- |
| ✅ En uso | Confirmado en probe o Python |
| 🟡 Disponible | En dump; no integrado aún |
| ⚠️ Inestable | A veces vacío, sentinel o depende del escenario |
| ❌ No autopiloto | Existe pero no aporta al frenado/calibración de mandos |

**Unidades TSW (observadas):**

| Magnitud | Unidad en API | Conversión útil |
| --- | --- | --- |
| Velocidad (`speedLimit`, etc.) | m/s | × 2.236936 → mph |
| Distancias (`distanceTo*`) | cm | ÷ 100 → m |
| Gradiente (`gradient`) | % | + subida, − bajada (convención `train_state`) |
| Altura (`height` en TrackData) | unidades UE (≈ cm) | perfil de vía, no % pendiente |

**Sentinel `3.402823e+38`:** valor “sin límite” / no aplicable (`float` máximo). Ignorar en
lógica de autopiloto.

---

## Árbol de nodos (3 endpoints)

```text
```

Todos son **solo lectura** (`writable: false` en el dump).

---

## `DriverAid.Data`

**HTTP:** `GET /get/DriverAid.Data`
**Lua:** `controller:GetDriverAidData(driverAid)` — mismos campos con distinta capitalización
(ej. HTTP `gradient` ↔ Lua `driverAid.gradient`).

### Velocidad y límites

| Campo | Tipo | Estado | Qué es | Uso autopiloto / calibración |
| --- | --- | --- | --- | --- |
| `speedLimit` | `{ value: m/s }` | ✅ | Límite de velocidad **aplicable ahora** al tren | Comparar con `speed_limit_ms` del probe; decisor P1/P2 |
| `speedLimitSeen` | bool | 🟡 | El juego considera que hay dato de límite válido | Filtro de confianza |
| `trackMaxSpeed` | `{ value: m/s }` | 🟡 | Techo de la vía (sin timetable/tren) | Suele coincidir con `speedLimit` en tramo simple |
| `formationMaxSpeed` | `{ value: m/s }` | ⚠️ | Límite del consist / vehículo | A veces sentinel; en otra sesión: 62.6 m/s (~140 mph) |
| `serviceMaxSpeed` | `{ value: m/s }` | ⚠️ | Límite del horario/servicio | A menudo sentinel si no aplica |
| `currentSpeedLimitSource` | string | 🟡 | Origen del límite activo | Ej. `TrackSpeedLimit`, `TemporarySpeedRestriction` |
| `distanceToNextSpeedLimit` | number (cm) | ✅ | Distancia al **próximo** cambio de límite | Probe `dist_limit_cm` ~20 Hz; HTTP fallback |
| `nextSpeedLimit` | `{ value: m/s }` | ✅ | Valor del próximo límite (primer cambio) | Probe `next_limit_ms`; P1 planning |
| `nextSpeedLimitPosition` | `{ x,y,z }` | 🟡 | Posición mundo del primer cambio | Debug / mapa |
| `nextSpeedLimits[]` | array | ⚠️ | Cola HTTP (muchos carteles, a menudo el mismo mph) | **Probe: no.** Ver [Investigar 2.º límite](#investigar-2º-límite-lim2) |
| `nextSpeedLimits[].restrictionType` | string | 🟡 | Tipo de restricción | Ej. `TrackPropertySpeedLimit` |
| `nextSpeedLimits[].value` | `{ value: m/s }` | 🟡 | Límite en ese punto | HTTP anidado `value.value` |

**Ejemplo dump:** `speedLimit.value` = 20.12 m/s ≈ **45 mph** (coherente con Class 323 en
Cross-City).

### Investigar 2.º límite (`lim2`)

**Decisión 2026-08-28:** el autopilot usa **un** próximo límite (escalares Lua
`DistanceToNextSpeedLimit` + `NextSpeedLimit` → `dist_limit_cm` / `next_limit_ms`). No se
publica `dist_limit2_*` hasta que haya lectura fiable.

**Qué sí hay en HTTP** (RailBridge / `DriverAid.Data`, p.ej.
`tsw-api-export-DriverAid-20260828T002847Z.json`):

- `nextSpeedLimits[i].distanceToNextSpeedLimit` es un **float cm**.
- `nextSpeedLimits[i].value.value` es m/s.
- El **2.º elemento no es `lim2`**. Suele ser otro cartel **al mismo mph** (mismo 55 a ~50 m).
  El primer **cambio de cifra** (p.ej. 45 mph) puede ir **kilómetros** más adelante.

**Qué hace UE4SS (`GetDriverAidData`, probe `20260828i`, log `023813`):**

- Padre: `DistanceToNextSpeedLimit=number`, `NextSpeedLimit=table` → **1 límite OK**
  (`n2=false`, `dist1_cm≈249579`, `next_limit_ms=24.5872` ≈ 55 mph).
- `NextSpeedLimits` es `table` con `foreach_n=2`, pero cada ítem es `userdata`:
  `arr1 d=nil ms=nil`. Sin `ForEachProperty`/`Get` en el tick (hitch ~2,7 s).
- Mezclar `foundSpeedLimits` con la cola **no**: misma query, otro envase → `lim2` falso.

**Pistas para más adelante (no implementar ahora):**

1. HTTP **solo** `GET DriverAid.Data.nextSpeedLimits` (~2 s), fusionar el primer `value`
   distinto del 1.er cartel; velocidad/palanca siguen en el probe.
2. Tecla F-key: `ForEachProperty` **una vez** sobre `arr[1]`/`arr[2]` (nunca en `ReceiveTick`).
3. Probar `GetPropertyValue("distanceToNextSpeedLimit")` en el ítem si UE4SS lo expone.

Parser Python `parse_driver_aid_planning` ya entiende la cola HTTP; el probe no la rellena.

### Gradiente y pendiente

| Campo | Tipo | Estado | Qué es | Uso |
| --- | --- | --- | --- | --- |
| `gradient` | number (%) | ✅ | Pendiente de vía en el punto del tren | `gradient_pct` en probe y learner; distancia de frenado |

**Lua (probe):** `driverAid.gradient` tras `GetDriverAidData`.
**Python:** `_parse_gradient_pct()` en `tsw_telemetry_source.py`; fallback HTTP si el probe no trae
el campo.

**Validado Class 323:** HUD ↔ probe `+1.0 %` en subida (2026-08-18).

### Señales

| Campo | Tipo | Estado | Qué es | Uso |
| --- | --- | --- | --- | --- |
| `signalSeen` | bool | 🟡 | Hay señal relevante en el query | — |
| `distanceToSignal` | number (cm) | 🟡 | Distancia a la señal consultada | **Pendiente C1** — no en GetData ni `TrainState` |
| `signalAspectClass` | string | 🟡 | Aspecto actual | Ej. `Stop`, `Clear` — cablear a `evaluate_signal_brake` |
| `bSignalIsPermissive` | bool | 🟡 | Señal permisiva (puede pasar con precaución) | — |
| `signalPropertyGuid` | string | 🟡 | ID interno de la señal | Debug / correlación editor |
| `nextSignalPosition` | `{ x,y,z }` | 🟡 | Posición de la señal | — |
| `nextSignalProperty` | `{ ribbonReference, propertyReference }` | ❌ | Referencias internas DTG | No usar en scripts |
| `nextSignals[]` | array | 🟡 | Varias señales adelante | `value` (aspecto), `distanceToNextSignal`, posición |

### Consulta interna (`trackRestrictionQuery`)

Bloque de **configuración del motor de búsqueda** hacia delante, no telemetría limpia para UI.

| Campo | Qué es | Uso |
| --- | --- | --- |
| `searchDirection` | `Forwards` / `Backwards` | Dirección de búsqueda |
| `maxSearchDistance` | Alcance (cm) | Ej. 10000 cm = 100 m en dump |
| `maxReturnedSignals` / `maxReturnedSpeedLimits` | Cuántos resultados pide | 4 en dump |
| `bWholeFormation` | Considerar todo el tren | bool |
| `foundSignals` / `foundSpeedLimits` | Resultados (a veces vacíos en snapshot) | Diagnóstico |
| `outCurrentTrackSpeedLimit` | Salida interna | A menudo sentinel |
| `speedCurveFlags`, `signalFlags`, etc. | Flags Unreal | Ignorar salvo investigación |

**Estado:** ❌ para autopiloto directo; útil solo para entender por qué `nextSpeedLimits` a veces
viene vacío.

---

## `DriverAid.TrackData`

**HTTP:** `GET /get/DriverAid.TrackData`
**Lua:** no expuesto en el probe actual (habría que llamar API HTTP o encontrar equivalente Lua).

### `trackHeights[]` — perfil vertical (no usado en TSW6)

**Qué es:** puntos de **elevación del rail adelante** (cota Z en el mundo UE), no peso del tren ni
pendiente %. Cada muestra: `distanceToHeight` (cm adelante), `height`, `bTunnelFound` (túnel).
`lastPlayerPosition` = el punto en la posición actual.

| | `gradient` (`Data`) | `trackHeights` (`TrackData`) |
| --- | --- | --- |
| Mide | Pendiente **ahora** (%) | Forma del trazado **adelante** |
| TSW6 | ✅ GetData → P1 | ❌ no leído |
| UK pasajero | Suele bastar | No prioritario |
| Freight NA | ✅ + learner | Solo si rampas largas fallan tras [masa](DASTSC_PARITY.md) |

**Ejemplo:** `gradient +1 %` = subo ahora · `trackHeights` = a 800 m empieza una rampa larga.

De `TrackData` solo usamos `markers[]` (andenes). El perfil vertical queda en la API del juego; el
autopilot no lo consulta.

### Estaciones y andenes

| Campo | Tipo | Estado | Qué es | Uso |
| --- | --- | --- | --- | --- |
| `markers[]` | array | ✅ | Paradas **programadas** del servicio | `markerName` + distancia |
| `markers[].markerType` | string | ✅ | Siempre `Platform` en UK (no «market») | Filtro de tipo |
| `markers[].markerName` | string | ✅ | Ej. `Lichfield City, andén 2` | Próxima parada |
| `markers[].stationName` | string | 🟡 | Nombre corto estación | — |
| `markers[].distanceToStationCM` | number (cm) | 🟡 | Distancia al marcador | Fin de andén; **no** es el tablón `car_stop` |
| `markers[].platformLength` | number (cm) | 🟡 | Longitud andén | Ventana FSM STOPPED |
| `markers[].distanceToStation` | `{ x, y }` | 🟡 | Coordenadas internas | — |
| `stations[]` | array | 🟡 | Geometría de andén (sin nombre) | **No** usar como parada |

**Integración HUD (2026-08-23):** `parse_track_data_stations` lee solo `markers[]` con
`markerType=Platform`. El autopilot filtra con `tsw_hud.db` (`hud_timetable.py`); si TrackData
muestra andenes de dirección incorrecta, usa distancias desde `car_stop_signs` (`source: hud_geo`).
Ver [HUD_TIMETABLE.md](HUD_TIMETABLE.md).

**Estado:** ✅ planning comercial con HUD DB; 🟡 distancia along-track solo cuando el nombre coincide.

---

## `DriverAid.PlayerInfo`

**HTTP:** `GET /get/DriverAid.PlayerInfo`

| Campo | Tipo | Estado | Qué es | Uso |
| --- | --- | --- | --- | --- |
| `playerProfileName` | string | ❌ | Perfil guardado TSW | Logs |
| `currentServiceName` | string | ✅ | Código servicio | Ej. `2R17` — match en `tsw_hud.db` |
| `cameraMode` | string | ❌ | Ej. `FirstPerson_Driving` | — |
| `currentTile` | `{ x, y }` | ❌ | Tile mundo | Debug |
| `geoLocation` | `{ latitude, longitude }` | ✅ | WGS84 aproximado | Desambiguar horario HUD por posición |

**Estado:** `geoLocation` + `currentServiceName` necesarios para `schedule_source=hud_db`.

---

## Qué NO está en DriverAid (mandos y frenos)

Para **calibrar frenos** (`aprender.bat`, matrices de muescas) necesitas el **vehículo**, no
DriverAid:

| Dato | Dónde (HTTPAPI) | Dónde (probe Lua) |
| --- | --- | --- |
| Handle combinado UK (0–8) | `HUD_GetPowerHandle` | `power`, `handle_notch` |
| Freno tren | `HUD_GetTrainBrakeHandle` | `train_brake` |
| Freno locomotora | `HUD_GetLocomotiveBrakeHandle` | `loco_brake` |
| Freno dinámico | `HUD_GetElectricBrakeHandle` | `dyn_brake` |
| Velocidad | `HUD_GetSpeed` | `speed_ms` |
| Aceleración | `HUD_GetAcceleration` | `accel_ms2` |

**Escritura** de mandos (autopiloto): preferido **IPC** `SendCommand.txt` (`tsw_ipc_bus`) · fallback
`PATCH /set/DriverInput.*` (`tsw_command_bus`). Ver [DASTSC_PARITY.md](DASTSC_PARITY.md).

---

## Mapa rápido: calibración de frenos vs DriverAid

| Necesitas… | Fuente recomendada | DriverAid ayuda? |
| --- | --- | --- |
| Aceleración por muesca de freno | Probe `train_brake` / `handle_notch` + `accel_ms2` | No |
| Banda de gradiente en learner | Probe `gradient_pct` (o `DriverAid.Data.gradient` fallback) | **Sí** |
| Distancia de frenado | Velocidad + perfil + `gradient_pct` | **Sí** (gradiente) |
| Saber cuándo bajar límite | `speed_limit_ms` + probe / `nextSpeedLimits` | Parcial |
| Parar en andén (qué parada) | `tsw_hud.db` + `TrackData.markers` | ✅ con HUD DB |
| Distancia al tablón | `car_stop_signs` en HUD DB | ✅ planning · 🔄 P1 (HUD, no OCR) |

---

## Cómo refrescar este catálogo tras un update de TSW

1. Arrancar TSW6 con `-HTTPAPI` y cargar escenario en cabina.
2. Exportar de nuevo (RailBridge cache o `tsw_api_reader`):

   ```text
   ```

3. Comparar con este MD: campos nuevos, renombrados o que pasan a devolver `INVALID`.
4. En Lua: **F8** en cabina → `DriverAid dump` en `UE4SS.log`.

**Endpoints estáticos** (pueden desactualizarse):
`investigacion tsw 6\tsw_projects-main\...\endpoints\DriverAid_endpoints.json`

---

## Referencias en TSW6

| Archivo | Relación |
| --- | --- |
| `mods/TelemetryProbeMod/Scripts/main.lua` | `GetDriverAidData` → `speed_limit_ms`, `gradient_pct`, `dist_limit_cm` (1), `doors_dmi` |
| `tsw_telemetry_source.py` | `_poll_driver_aid_planning`: Data + TrackData + PlayerInfo (HTTP ~2 s) |
| `hud_timetable.py` | Lectura `tsw_hud.db`, `car_stop_signs` |
| `driver_aid_parser.py` | `parse_track_data_stations`, filtros parada |
| `tsw_ue4ss_reader.py` | `--api` compara probe vs HTTP |
| `docs/HUD_TIMETABLE.md` | Setup BD, validación in-game |
| `docs/ESTADO.md` | Tablero trabajo; estudio flujo pasos 1–3 |
| `docs/PENDIENTE_DYNAMICHUD.md` | Roadmap probe / IPC |
| `docs/TSW_HTTPAPI_INDEX.md` | Índice dumps HTTPAPI |
| `docs/CURRENTFORMATION_API.md` | Física tren (masa, aire, esfuerzos) |
| `docs/ARQUITECTURA.md` | Lectura UE4SS vs HTTPAPI |

---

## Bitácora de validación

| Fecha | Campo | Resultado |
| --- | --- | --- |
| 2026-08-18 | `gradient` HTTP + Lua | Class 323, correlación HUD OK |
| 2026-08-18 | `speedLimit` | Coherente con límite HUD (~45 mph) |
| 2026-08-18 | Dump completo | 3 endpoints, Cross-City / Lichfield |
| 2026-08-23 | `PlayerInfo` + HUD DB | `2R17` Cross-City, paradas `car_stop_signs` en planning |
| 2026-08-24 | `nextSpeedLimits` en probe | Intento 2 límites; revertido a 1 escalar (2026-08-28) |
| 2026-08-28 | 1 límite probe | `023813` + UE4SS: `lim`/`next_lim` OK; TArray `d=nil`; `lim2` aparcado |

*Pendiente doc:* validar mismos campos en **BNSF SD40-2**; sesión **señales** (C1) antes de marcar
✅.
