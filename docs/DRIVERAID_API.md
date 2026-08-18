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
| `distanceToNextSpeedLimit` | number (cm) | 🟡 | Distancia al **próximo** cambio de límite | Frenado anticipatorio (futuro); dump: ~200 m |
| `nextSpeedLimit` | `{ value: m/s }` | 🟡 | Valor del próximo límite (primer cambio) | Planning |
| `nextSpeedLimitPosition` | `{ x,y,z }` | 🟡 | Posición mundo del primer cambio | Debug / mapa |
| `nextSpeedLimits[]` | array | 🟡 | Cola de cambios de límite adelante | Cada item: `distanceToNextSpeedLimit`, `value`, `restrictionType`, posición |
| `nextSpeedLimits[].restrictionType` | string | 🟡 | Tipo de restricción | Ej. `TrackPropertySpeedLimit` |
| `nextSpeedLimits[].value` | `{ value: m/s }` | 🟡 | Límite en ese punto | — |

**Ejemplo dump:** `speedLimit.value` = 20.12 m/s ≈ **45 mph** (coherente con Class 323 en
Cross-City).

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
| `distanceToSignal` | number (cm) | 🟡 | Distancia a la señal consultada | ~600 m en dump |
| `signalAspectClass` | string | 🟡 | Aspecto actual | Ej. `Stop`, `Clear`, `Approach` |
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

### Posición y perfil

| Campo | Tipo | Estado | Qué es | Uso |
| --- | --- | --- | --- | --- |
| `lastPlayerPosition.height` | number | 🟡 | Altura absoluta vía en posición actual | Perfil vertical |
| `lastPlayerPosition.distanceToHeight` | number (cm) | 🟡 | Distancia al punto de muestreo | — |
| `lastPlayerPosition.bTunnelFound` | bool | 🟡 | Túnel detectado en query | — |
| `trackHeights[]` | array | 🟡 | Muestras de altura **adelante** a lo largo del ribbon | Curvas, túneles; `distanceToHeight`, `height`, `bTunnelFound` |

No sustituye a `gradient` para física de frenado (el gradiente ya viene en `Data.gradient`).

### Estaciones y andenes

| Campo | Tipo | Estado | Qué es | Uso |
| --- | --- | --- | --- | --- |
| `markers[]` | array | 🟡 | Puntos de interés con nombre | Paradas programadas |
| `markers[].markerType` | string | 🟡 | Ej. `Platform` | — |
| `markers[].markerName` | string | 🟡 | Ej. `Lichfield City, andén 2` | UI / planning |
| `markers[].stationName` | string | 🟡 | Nombre corto estación | — |
| `markers[].distanceToStationCM` | number (cm) | 🟡 | Distancia al marcador | Parada en andén (futuro) |
| `markers[].platformLength` | number (cm) | 🟡 | Longitud andén | — |
| `markers[].distanceToStation` | `{ x, y }` | 🟡 | Coordenadas internas | — |
| `stations[]` | array | 🟡 | Similar a `markers` sin nombre visible | Lista más cruda de plataformas |

**Estado:** 🟡 planning comercial; **no necesario** para calibrar frenos ni autopiloto por límite.

---

## `DriverAid.PlayerInfo`

**HTTP:** `GET /get/DriverAid.PlayerInfo`

| Campo | Tipo | Estado | Qué es | Uso |
| --- | --- | --- | --- | --- |
| `playerProfileName` | string | ❌ | Perfil guardado TSW | Logs |
| `currentServiceName` | string | ❌ | Código servicio | Ej. `2R17` |
| `cameraMode` | string | ❌ | Ej. `FirstPerson_Driving` | — |
| `currentTile` | `{ x, y }` | ❌ | Tile mundo | Debug |
| `geoLocation` | `{ latitude, longitude }` | ❌ | WGS84 aproximado | Mapa real |

**Estado:** ❌ para frenado; útil para identificar sesión en logs.

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

**Escritura** de mandos (autopiloto): `PATCH /set/DriverInput.*` — ver `tsw_command_bus` /
`handle_controller.py`. Futuro: `SendCommand.txt` (B4).

---

## Mapa rápido: calibración de frenos vs DriverAid

| Necesitas… | Fuente recomendada | DriverAid ayuda? |
| --- | --- | --- |
| Aceleración por muesca de freno | Probe `train_brake` / `handle_notch` + `accel_ms2` | No |
| Banda de gradiente en learner | Probe `gradient_pct` (o `DriverAid.Data.gradient` fallback) | **Sí** |
| Distancia de frenado | Velocidad + perfil + `gradient_pct` | **Sí** (gradiente) |
| Saber cuándo bajar límite | `speed_limit_ms` + (futuro) `nextSpeedLimits` | Parcial |
| Parar en andén | `TrackData.markers` | Futuro |

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
| `mods/TelemetryProbeMod/Scripts/main.lua` | `GetDriverAidData` → `gradient`, `SpeedLimit` |
| `tsw_telemetry_source.py` | Poll `DriverAid.Data`, parser `gradient` |
| `tsw_ue4ss_reader.py` | `--api` compara probe vs HTTP |
| `docs/PENDIENTE_DYNAMICHUD.md` | Roadmap probe / B4 |
| `docs/ARQUITECTURA.md` | Lectura UE4SS vs HTTPAPI |

---

## Bitácora de validación

| Fecha | Campo | Resultado |
| --- | --- | --- |
| 2026-08-18 | `gradient` HTTP + Lua | Class 323, correlación HUD OK |
| 2026-08-18 | `speedLimit` | Coherente con límite HUD (~45 mph) |
| 2026-08-18 | Dump completo | 3 endpoints, Cross-City / Lichfield |

*Pendiente:* validar mismos campos en **BNSF SD40-2** y tras próximo parche TSW.
