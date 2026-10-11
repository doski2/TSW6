# M3a MTA — dumps HTTP (investigación) vs Lua probe / lab

**Origen datos escritorio:**
`C:\Users\doski\Desktop\investigacion tsw 6\trenes\m3a mta\`
**Captura:** 2026-10-03 (RailBridge / HTTPAPI, puerto típico `31270`) — **mismos timestamps** que
referencia
`scripts/tools/build_m3a_profile_from_exports.py` (caché RailBridge equivalente).

**Contrato producción:** [CANAL_CONTROL.md](../CANAL_CONTROL.md) · **Lua tick:** TelemetryProbeMod ·
**Lab Lua:** ApiExplorerMod F5–F7 · **Comparativa 323:**
[COMPARATIVA_323_M3A.md](COMPARATIVA_323_M3A.md).

---

## Archivos en la carpeta (qué es cada uno)

| Archivo                                                     | Raíz HTTP              | Nodos (resumen crawler)  | Rol                                          |
| ----------------------------------------------------------- | ---------------------- | ------------------------ | -------------------------------------------- |
| `tsw-api-export-CurrentFormation-20261003T153131Z.json`     | `CurrentFormation/0`   | ~3305 nodos              | Simulation, puertas, MC, frenos aire, ejes   |
| `tsw-api-export-CurrentDrivableActor-20261003T152838Z.json` | `CurrentDrivableActor` | ~413                     | `Function.HUD_Get*` (catálogo funciones HUD) |
| `tsw-api-export-DriverInput-20261003T154503Z.json`          | `DriverInput`          | ~46                      | Mandos jugador (`MasterController`, …)       |
| `tsw-api-export-DriverAid-20261003T154532Z.json`            | `DriverAid`            | 1                        | `Data` + **`TrackData`** (markers, alturas)  |
| `tsw-api-export-Player-20261003T152818Z.json`               | `Player`               | —                        | Posición / contexto jugador                  |
| `tsw-api-export-VirtualRailDriver-*.json`                   | VRD                    | —                        | Conductor virtual                            |
| `tsw-api-export-TimeOfDay-*.json`                           | Tiempo                 | —                        | No P1                                        |
| `tsw-api-export-WeatherManager-*.json`                      | Clima                  | —                        | No P1                                        |

---

## Tres capas (no confundir)

```text
```

---

## Comparativa — qué sacamos del tren y qué usamos ya

Leyenda: **Probe** = clave en `GetData.txt` · **HTTP prod** = Python `tsw_telemetry_source` /
planning ·
**Lab** = exports ApiExplorer · **Solo archivo** = útil investigación, no cableado tick.

| Dato / tema                         | En dumps HTTP (M3a MTA)                                                                           | Probe Lua (repo)                            | Lab Lua                             | Uso producto hoy                                 |
| ----------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------- | ----------------------------------- | ------------------------------------------------ |
| Velocidad, aceleración              | `HUD_GetSpeed`, `HUD_GetAcceleration` en actor                                                    | `speed_ms`, `accel_ms2`                     | F5                                  | **Probe** P1                                     |
| Límite vigente, gradiente           | `DriverAid.Data` (`speedLimit`, `gradient`)                                                       | `speed_limit_ms`, `gradient_pct`            | F7                                  | **Probe** + planning                             |
| 1.er cartel adelante                | `Data` distancias/límites                                                                         | `dist_limit_cm`, `next_limit_ms`            | F7                                  | **Probe** `limit_brake`                          |
| Señal US                            | `signalAspectClass`, `distanceToSignal`                                                           | `signal_red`, `signal_dist_cm` (mapeo C1)   | F7                                  | **Probe** (validar MNR)                          |
| **Amperímetro**                     | `HUD_GetAmmeter` (actor)                                                                          | **`amps`**                                  | F5                                  | **Probe** log (`amp.bat`); no regla P1           |
| Mandos HUD (freno tren/loco/din)    | `HUD_GetTrainBrakeHandle`, …                                                                      | `train_brake`, `loco_brake`, `dyn_brake`    | F5                                  | Display / contexto; MC usa `mc_input`            |
| **Master Controller**               | `CurrentFormation/0/MasterController.*`, `DriverInput/MasterController.*`                         | **`mc_input`** (prop `CurrentInputValue`)   | F6 3 levers                         | **Probe** + IPC `MasterController`               |
| Agujas freno / MR                   | `HUD_GetBrakeGauge_1/2`                                                                           | `brake_cyl_bar`, `brake_g1_*`, `mr_bar`     | F5 gauges                           | **Probe** tendencia aire (≠ Simulation)          |
| Presión Simulation                  | `Simulation/BrakeCylinder_*`.Pressure_BAR, `BrakeCylinder_Direct_P`, tuberías MR/BP               | No en tick (HUD primero)                    | `formation_http` correlator         | **Solo lab** / estudio; doc PLAN_API L0.6g       |
| Esfuerzo eje / TM                   | `Simulation/Axle_*/*/NetTractiveEffort`, `TM_*/Driveshaft.*`                                      | No (congelado P1)                           | F5 `simulation_traction` + Shift+F5 | **Lab** — ver § tracción L0.6d                   |
| Masa formación                      | `ClampPowerInput.Mass` (323 documentado)                                                          | —                                           | formation HTTP                      | **No aparece** en dump M3a buscado; poll F-B off |
| **Puertas**                         | `PassengerDoor_BL/BR/FL/FR`, `BP_NYH_M3a_PassengerDoorManager`                                    | **`doors_telem`** (hijos `PassengerDoor_*`) | F6 `lua.doors[]`                    | **Probe** (FACT `001325`); F6 omitido M3a        |
| Puertas DMI                         | —                                                                                                 | `doors_dmi`                                 | —                                   | Probe fallback FSM                               |
| Patinaje / bloqueo tracción         | `HUD_GetIsSlipping`, `HUD_GetIsTractionLocked`                                                    | `is_slipping`, `traction_locked`            | F5                                  | Log probe                                        |
| Paradas / andén                     | **`DriverAid.TrackData.markers[]`** (ej. North White Plains, `markerType: Siding`)                | No en GetData tick                          | F7 sin TrackData                    | **HTTP ~2 s** + `tsw_hud.db`                     |
| Perfil altura vía                   | `TrackData.trackHeights[]`                                                                        | No tick                                     | —                                   | **Solo HTTP** (planning/contexto)                |
| ATC / ACSES MNR                     | `BP_NYH_MNR_M3A_ACSES_ATC_V5` (frenos tubo, supresión)                                            | No                                          | —                                   | **Solo archivo** — no P1                         |
| Clima / hora                        | WeatherManager, TimeOfDay                                                                         | No                                          | —                                   | Ignorado P1                                      |
| **Confort accel/decel (blueprint)** | `RailVehiclePhysicsComponent0.Property.MaxComfortableAcceleration` / `MaxComfortableDeceleration` | No (no GetData)                             | Dump DrivableActor / Formation      | **Solo investigación** — ver § abajo             |

---

## Esfuerzo tractivo — L0.6d (HTTP sí; HUD no; Lua a revalidar)

**Qué dice el repo hoy** ([PLAN_API_EXPLORER §
L0.6d](PLAN_API_EXPLORER.md#l06d--esfuerzo-tractivo-no-hud--cerrado-http--lua-bloqueado),
[CURRENTFORMATION_API](../reference/CURRENTFORMATION_API.md#debate-hud_gettractiveeffort)):

- **`HUD_GetTractiveEffort`:** la UFunction existe; en **323** `TractiveEffort (N)` suele **0** (a

  veces `BrakeEffort` útil **parado** en B1–B2). **No** es fallo del mod — aguja no cableada.

- **`Simulation/Axle_1_1/Axle.NetTractiveEffort` (HTTP):** en 323 con potencia **+651 N**

  (`20260901T210515Z`); en patinaje **≈ −19,5 N** (`214213Z`). Ruta anidada
  `…/Axle_1_1/Axle.NetTractiveEffort` — la plana `Axle_1_1.NetTractiveEffort` suele fallar.

- **Shift+F5 `traction_probe` (323):** `index_ok` pero **`fields_by_via` vacío** en Lua (Simulation

  bloqueado en tick UE4SS, igual que presión en explorer antiguo).

- **P1 / producto:** esfuerzo tractivo **congelado** en [PLAN_V2](PLAN_V2.md) — no GetData; frenado

  usa `accel_ms2`, `mc_input`, aire. La tracción interesa para **aceleración suave** (MC), no para
  decel aprendida.

**FACT dump M3a `CurrentDrivableActor-20261003T152838Z`** (instante de captura — anotar MC/potencia
en notas si repites):

| Ruta HTTP (drivable)             | `NetTractiveEffort` (N)                | Notas                                           |
| -------------------------------- | -------------------------------------- | ----------------------------------------------- |
| `Simulation/Axle_1_1/Axle`       | **−26,06**                             | Par con `NetTorque_NM` ≈ 72                     |
| `Simulation/Axle_2_1/Axle`       | **+26,06**                             | Signo opuesto (bogie)                           |
| `Simulation/Axle_*_2/Axle`       | ±26                                    | Cuatro ejes en M3a (no solo `_1_1`/`_2_1`)      |
| `Simulation/Axle_*/Wheel`        | ±28,4                                  | Distinto signo que `Axle` en algunos ejes       |
| `Simulation/TM_*_*/Driveshaft`   | ±2                                     | Motor/tracción eléctrica — candidato diesel/EMU |
| `Function.HUD_GetTractiveEffort` | **SKIPPED_UNSAFE** en crawl RailBridge | No sustituye F5 Lua                             |

**Retest Lua (campo / lab):**

1. **F5** × 3 — parado neutro, **tracción MC** clara, **freno B2** en marcha ~15 mph; guardar

   `hud_batch.json` → clave nueva **`lua.simulation_traction`** (ApiExplorer build con
   `read_simulation_traction_probe` en `hud_batch.lua`).

2. **Shift+F5** `formation` — misma secuencia; revisar `traction_probe` (ahora incluye ejes

   `Axle_1_2`/`Axle_2_2` y subnodo `VirtualWheel`).

3. **Criterio éxito Lua:** algún `fields_by_via.Axle.NetTractiveEffort` (o `Wheel`) **≠ 0** y

   coherente con HTTP en la misma postura (correlator o GET manual).

4. Si Lua sigue vacío y HTTP responde → mantener **catálogo HTTP** (~2 s o poll lento); no meter en

   probe 20 Hz sin decisión D2.

Tarea en cola: [INVESTIGAR.md § Tracción
L0.6d](INVESTIGAR.md#tracción--nettractiveeffort-por-lua-l06d-m3a).

---

## Confort de aceleración / deceleración (investigación, no P1 freno)

**Contexto producto:** el frenado P1 y el **aprendizaje de decel por muesca** en M3a/323 van bien;
**no** hay plan de cablear estos campos al coordinador de freno. El hueco abierto del usuario es más
**tracción / aceleración suave** (MC, salidas de estación, creep) que frenado.

**FACT (dump `CurrentDrivableActor-20261003T152838Z`, mismo valor en coches
`CurrentFormation/0`…`7`):**

| Propiedad HTTP (relativa al drivable)                                | Valor captura | Unidad |
| -------------------------------------------------------------------- | ------------- | ------ |
| `…/RailVehiclePhysicsComponent0.Property.MaxComfortableAcceleration` | **0,44704**   | m/s²   |
| `…/RailVehiclePhysicsComponent0.Property.MaxComfortableDeceleration` | **0,44704**   | m/s²   |

**INFERENCE:** 0,44704 ≈ `MPH_TO_MS` del repo → **~1 mph/s** de cambio de velocidad como techo de
“confort” en blueprint DTG (doc modding: límite antes de molestar pasajeros / daño carga; puede
afectar stats de escenario).

**No confundir con:**

| Señal                                     | Qué es                                                                                         |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `accel_ms2` (probe `HUD_GetAcceleration`) | Aceleración **instantánea** en marcha; el learner P1 usa su magnitud al **frenar** (`-accel`). |
| `MAX_DECEL_MS2` / perfil aprendido        | Planificación **freno servicio** — por encima del techo “comfort” (~1,07 m/s² base 323).       |
| `MaxComfortable*`                         | Constantes de **diseño** del vehículo; hoy **sin** poll ni regla en `tsw6v2`.                  |

**UNKNOWN (validar en juego):** si el simulador **limita** el input del jugador/autopilot a esos
valores o solo los usa para puntuación de escenario. Experimento sugerido: misma sesión JSONL con
`accel_ms2` al acelerar fuerte en MC y al frenar B3; si `|accel_ms2|` supera ~0,45 m/s² de forma
estable, el confort blueprint **no** es el techo físico único.

**Uso futuro posible (aceleración, no frenos):** techo de referencia ~0,45 m/s² al diseñar rampas
MC/IPC, modo “conductor suave”, o comparar con `mc_input` + `amps` en salidas. Poll HTTP opcional
(arranque, no tick).

---

## Hallazgos M3a en HTTP (FACT del dump 20261003)

- **Puertas:** nombres UE **`PassengerDoor_BL/BR/FL/FR`** (+ manager blueprint NYH) — alineado con

  lista
  `PassengerDoor_*` del probe (no hace falta F6 para saber el prefijo en M3a).

- **MC:** árbol completo en `CurrentFormation/0/MasterController` y espejo en

  `DriverInput/MasterController`
(mismas funciones `GetCurrentInputValue`, notches, etc.) — el probe lee **propiedad** en tick, no
HTTP.

- **DriverAid.Data** en la captura: `speedLimit` ≈ 4,47 m/s (~10 mph), `signalAspectClass: Clear`,

  gradiente 0.

- **TrackData:** al menos un marker tipo **`Siding`** (clasificación North White Plains) — filtrar

  `Platform` en
  producción ([DRIVERAID_API.md](../reference/DRIVERAID_API.md)).

- **Simulation aire:** muchos nodos `BrakeCylinder_1/2`, `BrakeCylinder_Direct_P`, `Reservoir (MR)`

  con
`Pressure_BAR` — correlacionar con HUD en lab, **no** sustituir `brake_cyl_bar` del probe sin
evidencia.

---

## Qué ya teníamos en repo antes de esta carpeta

| Artefacto repo                                                         | Relación con escritorio                                                          |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `data/vehicles/m3a_mnr.json`                                           | Generado desde lab `20261005T210550Z` + **mismos dumps** 20261003 (script merge) |
| `logs/probe/20261007_*`                                                | Campo **posterior** — amps/puertas en GetData real (~20 Hz)                      |
| [RVM_Class323_M3a_LUA_HTTP.md](telemetry/RVM_Class323_M3a_LUA_HTTP.md) | Misma arquitectura capas; M3a § HTTP parcial                                     |
| [PLAN_AMPS_PUERTAS_20261006.md](PLAN_AMPS_PUERTAS_20261006.md)         | Cerrado en **probe**, no en HTTP crawl                                           |

---

## Qué **no** hace falta duplicar del HTTP en producción

1. Volcar **todo** `CurrentFormation` al tick (miles de endpoints) — hitch y sin contrato.
2. Sustituir **`doors_telem`** por polling HTTP a cada `PassengerDoor_*`.
3. Usar **presión Simulation** como única verdad si el HUD del probe ya da `brake_cyl_bar` / gauges.
4. Mezclar markers **`Siding`** con paradas de servicio sin filtro horario HUD.

---

## Si quieres archivar en el repo

Los JSON son grandes y **no** van en git por defecto. Opciones:

- Dejar en escritorio (referencia personal).
- Copiar a `data/reference/m3a_mta_http_20261003/` (añadir a `.gitignore` si pesa).
- RailBridge suele guardar copia en `%LOCALAPPDATA%\RailBridge\cache\api-dumps\` (mismos nombres).

---

## Relacionados

- [PROBE_LOGS.md](PROBE_LOGS.md) · [PLAN_ACTUACION_MC.md](PLAN_ACTUACION_MC.md) ·

  [DRIVERAID_API.md](../reference/DRIVERAID_API.md)
