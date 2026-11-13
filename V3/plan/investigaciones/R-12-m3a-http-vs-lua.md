# R-12 — M3A: qué expone el juego por HTTP y qué alcanza Lua

- **Estado:** Paso 1 hecho (2026-11-13, sin juego). Faltan los pasos 2 y 3.
- **Desbloquea:** catálogo y suscripción de la M3A ([0004](../decisiones/0004-el-mod-lee-todo-python-elige.md)),
  paquete `trenes/m3a/` ([0003](../decisiones/0003-estructura-por-tren-y-familia.md)), diseño del
  laboratorio V3, R-03 (latencia), R-11 (mapa de ruta).
- **Necesita juego:** el paso 1 no; los pasos 2 y 3 sí.

## Pregunta

La HTTPAPI del juego (vía RailBridge) enseña muchísimo, pero llega con retraso y no es fluida para
conducir. ¿Qué de eso se puede leer **desde Lua**, que es más rápido y fiable? Primero ver qué
expone; luego decidir qué interesa (v1: solo frenar).

## Método (paso 1, sin juego)

Se cruzan dos fuentes ya grabadas:

| Fuente | Qué es | Fecha |
| ------ | ------ | ----- |
| Volcados HTTP (RailBridge) | `Desktop\investigacion tsw 6\trenes\m3a mta\` — 8 ficheros, ~64 000 campos (todos los coches) | 2026-10-03 |
| Laboratorio Lua de V2 (ApiExplorerMod) | `data/lab_exports/exports/20261005T210550Z/` | 2026-10-05 |

Script: [datos/R-12/cruce_http_lua.py](datos/R-12/cruce_http_lua.py). Solo lee ficheros. Saca:

- `datos/R-12/todo.csv`: 9 515 campos del coche de cabina (`CurrentDrivableActor`), `DriverAid` y
  `DriverInput`. **No va a git** (1,3 MB); se regenera con el script.
- [datos/R-12/freno_v1.csv](datos/R-12/freno_v1.csv): **966 campos** que responden por HTTP y tienen
  pinta de servir para frenar. Columnas: grupo, componente, ruta HTTP, estado, valor, qué pasó en
  Lua.

## Resultados

### Resumen por grupo (solo campos de freno, `freno_v1.csv`)

| Grupo | Campos | ¿Lua lo intentó? |
| ----- | -----: | ---------------- |
| `Simulation/*` (aire, cilindros, zapatas, ejes, válvulas) | 276 | 30 sí, **falló**; 246 nunca |
| Otros componentes (`BrakeCharging`, `DeadmanFootSwitch`, `AlerterV2`, cut-outs, freno de mano…) | 244 | Nunca |
| `DriverInput` (espejo de los mandos) | 251 | Solo el MasterController, leído en el actor |
| **Seguridad ACSES/ATC** (`BP_NYH_MNR_M3A_ACSES_ATC_V5`) | 143 | **Nunca** |
| Mando `MasterController` | 24 | Sí, algunas propiedades |
| HUD (`HUD_Get*`) | 13 | Sí, 9 leídos (los otros 4 son de vapor/alerter) |
| Referencias a Simulation en el actor (`Property.Simulation_*`) | 7 | Nunca |
| `DriverAid` | 3 | `Data` sí; **`TrackData` solo HTTP** |

### Hallazgos

- FACT: **el HUD va mejor por Lua que por HTTP.** RailBridge salta todas las `HUD_Get*`
  (`SKIPPED_UNSAFE`); Lua leyó 16 (velocidad, aceleración, agujas de freno, mandos, amperímetro…).
- FACT: **la aguja roja del HUD es la presión del cilindro de freno.** `HUD_GetBrakeGauge_1.RedNeedle`
  (Lua) = 101 305,8 Pa, igual que `Simulation/BrakeCylinder_1.Pressure` (HTTP) en reposo. Para frenar
  puede bastar el HUD. (INFERENCE: hay que confirmarlo con freno aplicado; los dos datos son de días
  distintos.)
- FACT: **Lua no pudo leer `Simulation/*`.** Encuentra el componente y los nodos, pero el nodo hijo
  sale no válido y sin campos. Por HTTP sí: `BrakeCylinder_1/2`, `BrakeCylinder_Direct_P`,
  `BrakeCylinderEMG`, `BP (AirPipe)`, `MR (AirPipe)`, `Reservoir (MR)` con `Pressure_BAR`, y un nodo
  `A-23 Braking Computer`.
- FACT (**pista nueva**): el propio tren guarda **referencias** a Simulation como propiedades del
  actor, p. ej. `Property.Simulation_BrakeCylinder_1_Pressure` =
  `{nodeReference:{componentName:"Simulation", nodeName:"BrakeCylinder_1"}, parameterReference:{name:"Pressure"}}`.
  Hay 24 así (cilindro, válvula de emergencia, aceleración del HUD, patinaje, motores…).
  INFERENCE: el blueprint lee Simulation **a través de estas referencias**; si Lua consigue usar
  la misma vía (una función que reciba la referencia), se abre la puerta que en V2 estaba cerrada.
  UNKNOWN: qué función es; hay que buscarla en el paso 2.
- FACT: **el sistema de seguridad ACSES/ATC está entero por HTTP y Lua nunca lo miró.** Datos útiles
  para frenar sin que el tren se castigue a sí mismo: `ACSES_SpeedCurveDecelerationRate` = 0,335 m/s²,
  `ACSES_AlertLimit` / `ACSES_PenaltyLimit` (1,34 / 2,68 m/s de margen), `bACSES_IsOverspeed`,
  `ACSES_PenaltyMAS_mps`, `ACSES_WarningSpeed_mps`, `ATC_Aspect`, `ATC_SignalSpeed`,
  `bATC_IsOverspeed`, `PTS_StopState`. Si el autopiloto pasa la curva de ACSES, el tren aplica freno
  de penalización.
- FACT: **`DriverAid.TrackData` (paradas y alturas de vía) sigue siendo solo HTTP.** Es lo que
  necesita el mapa de ruta ([R-11](README.md)). Como no hace falta en cada ciclo, puede quedarse en
  HTTP y pedirse despacio.
- FACT: **mandos**: `MasterController` es un `IrregularLeverComponent` con 7 muescas leídas desde Lua
  (coincide con `data/vehicles/m3a_mnr.json`). En el actor hay además `Enum_Brake = 3`,
  `Enum_Throttle = 2`, `Enum_BrakeCharging = 8`, que parecen índices de función de mando. UNKNOWN:
  qué significan.
- FACT: muchos campos HTTP dan `INVALID` o `SKIPPED_UNSAFE` (~45 % del coche de cabina): el
  crawler no los evalúa por seguridad. Que HTTP no lo dé **no** quiere decir que no exista.

## Siguiente paso

**Paso 2 (en el juego, con el laboratorio V3):**

1. Volcado HTTP nuevo al empezar (los de octubre pueden estar viejos tras actualizaciones).
2. Desde Lua, probar en este orden: (a) ACSES/ATC, (b) las referencias `Property.Simulation_*`
   (buscar la función que las resuelve), (c) `BrakeCharging` y `Enum_*`.
3. Grabar a la vez HTTP y Lua con hora de cada lectura, en cinco posturas: parado neutro, B1, B2, B3
   y en marcha frenando. Comparar valores y medir retraso (también cierra parte de R-03).

**Paso 3:** clasificar cada campo (`usado` / `candidato` / `descartado` / `desconocido`) según
[README § Después de recoger datos](README.md#después-de-recoger-datos) y analizar a fondo los
candidatos.
