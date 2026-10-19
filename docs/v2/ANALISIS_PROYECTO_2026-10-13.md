# Análisis del proyecto V2 — 2026-10-13 (actualizado 2026-10-15)

Alcance: `V2/tsw6v2/` (56 módulos + 5 en `bridge/`, ~18,2 k líneas; 40 ficheros de test, ~9,5 k
líneas). Sin cambios de código en este análisis.
Evidencia clasificada según `00-tsw6-core.mdc`: FACT = código leído o medido en logs; INFERENCE =
deducción; UNKNOWN = no demostrado.

Cambios respecto a la versión del 2026-10-13: tamaños actualizados (§1), nueva sección de
arquitectura multi-locomotora (§2) y hallazgos de las sesiones del 2026-10-15 (§7). Los apartados
de duplicados, riesgos y mejoras (§3–§6) siguen vigentes y no se han tratado.

## 1. Tamaño y complejidad (FACT)

Archivos más grandes (líneas):

| Líneas | Archivo              | Nota                                                    |
| ------ | -------------------- | ------------------------------------------------------- |
| 1680   | `session_report.py`  | HTML + cálculo; candidato a partir (render vs métricas) |
| 1304   | `decision.py`        | Núcleo P1; concentra cartel, andén, RELEASE y COAST     |
| 1023   | `p1_station_gate.py` | FSM de estación                                         |
| 981    | `loop.py`            | Bucle agente; envío IPC + estado                        |
| 940    | `vehicle_package.py` | Datos de vehículo (53 funciones, 19 helpers `mc_*`)     |
| 822    | `station_plan.py`    | Perfil de parada en andén                               |
| 816    | `command.py`         | `BrakeCommand` y mandos IPC                             |
| 787    | `gui.py`             |                                                         |

## 2. ¿Separar por locomotora? Arquitectura multi-vehículo

Pregunta: hoy hay 2 vehículos (Class 323 y M3A) y faltan muchos más. ¿El código actual servirá
para todos y conviene separar ficheros?

### 2.1 Estado actual (FACT)

- Hay **dos paquetes de vehículo** en `data/vehicles/`: `class_323.json` (layout muesca combinada
  UK) y `m3a_mnr.json` (layout `combined` con palanca MC analógica). No hay ningún otro.
- La bifurcación entre ambos está **dispersa**: `uses_mc_analog_ipc(...)` aparece en 36 puntos
  (16 dentro de `vehicle_package.py` y 20 fuera): `loop.py` 5, `p1_station_gate.py` 4, `decision.py`
  3, `ipc.py` 3, `command.py` 2, y 1 en `gui_view.py`, `diagnostic.py` y `brake_cab.py`.
- Solo hay **dos modelos de aire**: `uk_emu` y `master_controller` (`brake_air_profile.py`).
- La región se decide por **cadenas de texto fijas** (`vehicle_route_fleet`, `vehicle_package.py:45`):
  `NYH`/`_MNR_` → `ny`; `BCC`/`CLASS323` → `uk`; cualquier otro → `None` (se confía sin validar).
- Los parámetros de física **por defecto** vienen de la 323 (`constants.py` abre con «Constantes del
  producto (323 combined UK)»). Desde 2026-10-15 cada paquete de vehículo puede traer un bloque
  `physics` (`max_decel_ms2`, `coast_decel_ms2`, `safety_margin`, `brake_transition_s`,
  `service_decel_frac`) y `decision.py` lo activa en cada tick (`physics.set_active_physics`). Los dos
  JSON llevan hoy los valores de la 323 (el de la M3A, marcado «heredado», sin medir). Siguen con
  el valor de la 323 los callers que no pasan `base_decel` explícito (p. ej. `autopilot_limit`) y
  los defaults de `limits`, `signal_*` y `station_plan`.
- La **estructura de la palanca** sigue siendo la de la 323: `NEUTRAL_NOTCH = 4`, `B1_NOTCH = 3`,
  escalones B1–B3 (`handle in (1, 2, 3)`, `_BRAKE_HANDLES = (0, 1, 2, 3)`) y la tabla de fracciones
  `plan.SERVICE_DECEL_FRAC_BY_HANDLE`. Ver §2.6.
- Lo que **sí** es por vehículo: el perfil aprendido (`logs/profiles/<vehicle>.json`, p. ej.
  `rvm_nyh_mnr_m3a-a_c.json`) y el mapeo de mandos IPC en el paquete.
- Fuentes de datos agnósticas al tren (FACT): `bridge/*` (GetData, IPC, HTTP), `planning_*`,
  `hud_db.py`, `track_stations.py` y `physics.py` no mencionan ningún vehículo concreto.

### 2.2 Qué asume hoy el motor P1 (INFERENCE)

Estos supuestos valen para 323 y M3A y no tienen por qué valer para otras locomotoras:

1. **Una sola palanca combinada** (tracción + freno) con **tres escalones de servicio** (B1–B3) y un
   neutro. No contempla freno de tren e independiente separados, ni locomotoras con acelerador y
   freno en ejes distintos.
2. **Servicio de pasajeros con paradas en andén** (`DriverAid.TrackData`, FSM `STOPPED` /
   `DEPARTING`). Una locomotora de mercancías no tiene esa lógica de parada.
3. **Deceleración tipo tren de cercanías** (`MAX_DECEL_MS2` de la 323) y masa por la formación vía
   HTTP. Un tren largo de mercancías o un diésel con freno neumático lento rompería los márgenes.
4. **Freno eléctrico solo como retención en amperios** (`amps < −1`), sin modelo propio.
5. **Dos regiones** (`uk`, `ny`). Material europeo (PZB/LZB) o de otras flotas no está contemplado.

No hay evidencia en el repositorio de que el motor se haya validado con un tercer vehículo
(UNKNOWN). Lo único comprobado es 323 + M3A.

### 2.3 Riesgo de seguir sin separar (INFERENCE)

- Cada locomotora nueva obliga a **tocar varios archivos grandes** (`decision.py`, `loop.py`,
  `p1_station_gate.py`, `command.py`, `ipc.py`) para añadir otra rama `if`. Hoy ya son 20 puntos
  fuera de `vehicle_package.py`; con 5 vehículos la lógica de cada rama quedaría entrelazada.
- Un arreglo pensado para la M3A puede romper la 323 sin que lo detecte un test: 21 de los 40
  ficheros de test mencionan 323 o M3A, pero no hay un conjunto común de pruebas que se ejecute
  contra cada paquete de vehículo.
- Las constantes de la 323 como valores por defecto dan resultados plausibles para cualquier tren
  y por eso pasan desapercibidas (la M3A frena con decel aprendida 0,3–0,5 m/s² mientras el motor
  planifica con 1,07 m/s² hasta que alguien fije el bloque `physics` de su JSON).

### 2.4 Propuesta

No hace falta partir ficheros ya. Lo que más pesa es **centralizar la decisión «qué vehículo es»**,
no mover código. Orden sugerido:

1. **Capacidades en el paquete de vehículo (sin mover ficheros).** *Hecho en parte (2026-10-15):*
   bloque `physics` con deceleración máxima, coast, margen, transición y fracciones por escalón,
   leído por `vehicle_physics()`. Falta: neutro y escalones de freno declarados en el JSON,
   `has_regen`, masa/formación por defecto, y medir los valores reales de la M3A.
2. **Interfaz `VehicleAdapter`.** Una clase pequeña con las operaciones que hoy se bifurcan con
   `uses_mc_analog_ipc`: construir el mando IPC, saber si el freno está aplicado, qué cuenta como
   neutro, cómo confirmar un escalón. Dos implementaciones iniciales (`uk_notch`, `mc_analog`).
   Los 20 puntos externos pasan a llamar al adaptador. Se hace de uno en uno, con los tests
   actuales como red de seguridad.
3. **Registro de flotas por datos.** Sustituir `vehicle_route_fleet` por un campo `fleet` o `region`
   en el JSON y detectar el vehículo por su `match`, no por prefijos escritos en código.
4. **Pruebas de contrato por vehículo.** Un único conjunto de pruebas parametrizado con cada paquete
   de `data/vehicles/` (parada en andén, soltar al salir, paso entre muescas). Cada vehículo
   nuevo debe pasarlas antes de darse por soportado.
5. **Solo entonces, reorganizar carpetas.** Cuando exista un tercer vehículo y los adaptadores sean
   estables: `core/` (física, planes, límites, andén), `vehicles/<layout>/` (adaptador + reglas),
   `io/` (bridge, IPC), `ui/` (GUI, informe). Hacerlo antes es mover código sin ganar claridad.

Prioridad: pasos 1 y 4 primero (no cambian comportamiento y dan seguridad); el 2 después, de uno en
uno; el 5 al final.

### 2.5 Qué probaría que funciona con otro tren (UNKNOWN, a validar)

Antes de prometer soporte a una locomotora nueva hace falta, como mínimo: lab de controles
(`VEHICLE_LAB.md`), un paquete JSON con sus escalones y fracciones, una sesión de calibración de
frenado y las pruebas de contrato del paso 4. Con los datos actuales no se puede estimar cuántos
vehículos distintos cabrían en los dos layouts existentes.

### 2.6 Muescas y palanca: por qué la M3A sigue usando escalones de la 323 (FACT / INFERENCE)

Estructura real de la palanca de la M3A, según la captura de laboratorio (`m3a_mnr.json`,
`MasterController`, `IrregularLeverComponent`):

| Índice | Valor                | Qué es                                  |
| ------ | -------------------- | --------------------------------------- |
| 1      | 0,0                  | Extremo de freno                        |
| 2      | 0,27 – 0,63          | Zona de freno **continua**              |
| 3      | 0,64                 | Clic fijo (freno más suave que sostiene)|
| 4      | 0,72                 | Neutro                                  |
| 5–7    | 0,85 / 0,90 / 0,95   | Tracción (escalones)                    |

Qué parte del código ya trata la palanca de la M3A como continua (FACT):

- **Parada en estación:** `mc_stop_brake_fraction` (`vehicle_package.py:656`, usado en
  `decision.py:839`) elige la fracción para parar sin pasar por B1/B2/B3.
- **Aprendizaje por posición:** `LearnerProfile.observe_mc_brake` guarda la decel por fracción
  (`decel_by_mc`, 0,29–0,63 en el perfil actual).

Qué sigue pensando en la palanca UK de la 323 (FACT):

- **Frenado por cartel** y emergencia: planifican con B1–B3 y el paquete los traduce con
  `brake_input` (`B1` 0,64, `B2` 0,45, `B3` 0,27).
- **Aprendizaje por muesca** (`v1_mixed`): tabla de decel por B1/B2/B3, no por fracción.
- **Estado de la palanca:** `lever` se obtiene cuantizando `mc_input` (0,64 → 3, 0,72 → 4,
  0,85 → 5; visible en los logs). FSM de andén, `platform_bleed` y `brake_cab` razonan con ese
  número.
- **Constantes:** `NEUTRAL_NOTCH`, `B1_NOTCH`, el rango 1–3 y `SERVICE_DECEL_FRAC_BY_HANDLE`.

Causa (INFERENCE): el motor se escribió para la 323 (palanca combinada de 7 posiciones) y la M3A
se acopló con una capa de traducción. La parte de parada en estación se rehízo para MC; el resto
se dejó con el modelo UK.

Modelo propuesto (INFERENCE, a validar tras las pruebas):

1. **El planificador pide una deceleración objetivo** (m/s²), no un escalón. Para cartel, estación,
   señal y emergencia.
2. **El adaptador del vehículo convierte decel → posición de palanca:**
   - M3A: interpola en la curva aprendida `decel_by_mc` (fracción continua); el clic 0,64 es el
     mínimo sostenible y el neutro 0,72 es «sin freno».
   - 323: elige la muesca más cercana según la tabla de fracciones del JSON.
3. **El JSON declara la estructura de la palanca**, no el código: `brake_zone` (continua o por
   pasos, con mínimo y máximo), `click`, `neutral`, pasos de tracción y fracciones por escalón.
   Desaparecen `NEUTRAL_NOTCH`, `B1_NOTCH` y `handle in (1, 2, 3)` de la lógica común.
4. **El aprendizaje se indexa por posición de palanca** (fracción para la M3A, muesca para la
   323), con la misma interfaz `predict_decel(posición, velocidad, pendiente)`.
5. **`lever` deja de ser un entero UK universal.** La FSM de andén pregunta al adaptador
   «¿freno aplicado?», «¿neutro?», «¿tracción pedida?».

Riesgo: toca frenado por cartel, FSM de andén, `platform_bleed`, aprendizaje y trazas a la vez.
Hacerlo **después** de validar las sesiones con los cambios actuales y con las pruebas de contrato
por vehículo (§2.4 paso 4) ya escritas, para poder comparar antes y después.

## 3. Duplicados (FACT)

- **Resuelto (2026-10-19): timeouts de ACK.** Una sola fuente, `constants.IPC_ACK_TIMEOUT_S` (0,35);
  `AGENT_ACK_TIMEOUT_S`, `ipc.DEFAULT_ACK_TIMEOUT_S`, los defaults `ack_timeout_s` de `ipc.py` y de
  `bridge/ipc_bus.py` (antes 0,12) la referencian. 546 tests en verde. El `timeout_s=0,12` de
  `wait_send_ack` es otro parámetro y se deja.
- **Resuelto: `PredictDecelFn`.** Ya solo se define en `plan.py`; el resto de módulos la importa
  (el análisis original contaba 7 definiciones; verificado 2026-10-19).
- **`main` en 2 módulos**: normal (puntos de entrada), sin acción.

## 4. Fallos y riesgos (FACT salvo indicado)

- **ACK ok sin confirmar palanca** (`loop.py`, `_notch_step_pending`): si el ACK es `ok` el
  pendiente no se activa, y el paso puede reenviarse si la palanca tarda en cambiar. Hueco conocido,
  bajo riesgo observado (5 cambios de palanca en 1547 ticks en 214529Z).
- **Excepciones amplias** (`except Exception`): `hud_schedule.py:64,76` y `planning_poller.py:361`.
  Ocultan errores; conviene registrar y tratar la causa.
- **Ventana de aprendizaje de 2 s** (`learn_quality.py`): cualquier cambio de muesca descarta la
  ventana entera (`notch_unstable`). Limita el aprendizaje de `mixed` (87 rechazos en 201122Z).
  Cambio de diseño pendiente de confirmación.
- **Rama MC y rama combinada** comparten `_brake_kind`/aprendizaje pero con tablas distintas; el
  riesgo es confusión de tablas (ya tratado con `brake_kind` explícito).

## 5. Mejoras propuestas (INFERENCE)

1. ~~Unificar timeouts de ACK~~ y 2. ~~`PredictDecelFn` única~~: hechos (ver §3).
3. Sustituir los `except Exception` por excepciones concretas, o registrar con `logging` antes de
   continuar.
4. Partir `session_report.py` en: métricas (sin HTML) y render HTML.
5. Confirmar la ventana de 2 s: reiniciar solo desde el último tick válido en lugar de borrar todo.
6. Cerrar el hueco del ACK ok: marcar pendiente también con ACK ok hasta que la palanca confirme el
   cambio.
7. Parámetros por vehículo y adaptador de vehículo (ver §2.4).

## 6. Pendiente de validación (UNKNOWN)

- Efecto real del pendiente de paso sobre la palanca en campo (solo 1 sesión evaluada).
- Si `v1_mixed` converge con varias sesiones limpias.
- Regla de 300 m de llegada/DEPARTING: sin segunda parada en campo.
- Comportamiento con un tercer vehículo (ver §2.5).

## 7. Hallazgos de las sesiones del 2026-10-15 (FACT salvo indicado)

Logs `20261015T184644Z` a `20261015T210604Z`, ruta `gct-mnr`, M3A.

- **Distancia a la estación.** `distanceToStationCM` de `DriverAid.TrackData` es el **fin del andén**,
  no el tablón de parada (`docs/reference/DRIVERAID_API.md:222`). Medido contra el HUD del juego:
  White Plains 15,5 m (HUD) frente a 133,4 m (app); Hartsdale ≈ 447 m frente a 481 m. El desfase
  cambia por estación (≈ 35 a ≈ 118 m), así que no es una constante ni solo el retardo HTTP.
- **Retardo HTTP.** La lectura de `TrackData` cambia cada 4,2 s de mediana (mínimo 3,9 s; la doc
  decía ~2 s). Se añadió `PLANNING_HTTP_LAG_S = 2.0` y `compensate_http_distance_m`
  (`planning_feed.py`). Efecto en campo: UNKNOWN.
- **OCR del HUD (medición, 2026-10-18).** El OCR se había descartado como control (`PLAN_V2` §4.4). Se añadió como medición: `--hud-ocr` graba `hud_ocr_m` en el JSONL y `scripts/analyze_hud_ocr.py` evalúa «corregir cada N capturas». Ver [HUD_OCR_MEDICION.md](HUD_OCR_MEDICION.md). Resultado en campo: UNKNOWN.
- **Dead-reckoning con límite de fps (2026-10-18).** Con el juego limitado a 50 fps el probe escribe un `seq` cada 60 ms (16,67 Hz), no cada 50 ms. Convertir `seq×50 ms` hacía avanzar la distancia ≈ 20 % de menos entre lecturas HTTP y dejaba plana la distancia en el 17 % de los ticks (micro paradas). Ahora el `dt` sale del reloj de pared y el `seq` solo detecta pausa (`PROBE_FROZEN_S`) o retroceso (`resolve_station_tick_dt`). Sin validar en juego. `active_t_ms` del informe sigue usando `seq×50 ms`. Diagnóstico de fluidez: `perf_ms` en el JSONL.
- **Parada corta y rodar en la aproximación final (2026-10-18, 181008Z).** Tres paradas de ocho quedaron 42-58 m antes del tablón: el clic del M3A frena ≈ 0,34 m/s² y desde 13 mph a 100 m bastan ≈ 0,17. El corte «no rodar con la parada en curso a < 100 m» (090737Z) lo impedía. Ahora `mc_station_roll_allowed` no corta por distancia, la banda de histéresis es proporcional (10 % de la distancia, 2-20 m) y `StationRollLatch` exige 3 s entre conmutaciones rodar↔frenar (simulado: parada a ≈ 6 m corto con 4-8 conmutaciones). Sin validar en juego. También: con el ancla HUD «stn≤1 m» es llegada al tablón, no marcador pasado (`MARKER_PASSED_MIN_MPH_BOARD`); causó la emergencia de Fleetwood.
- **Parada en estación fuera del horario (2026-10-18, 203040Z).** El servicio 500 no para en Tremont (horario de la BD: Fordham 05:27:00 → Harlem 125th 05:34:30). Dos causas: `PlayerInfo` fallaba de forma intermitente y el poll caía a `track_only` (sin filtro de horario; 50 298 ticks `hud_db` frente a 5 183 `track_only`), y si ninguna parada programada salía aún en `TrackData`, `apply_station_schedule` devolvía todas las estaciones. Ahora el poll usa el último servicio conocido (`service_name_hint`) y, tras cruzar alguna vez horario y `TrackData`, no ofrece estaciones no programadas (`fallback_all_when_unmatched`). Sin validar en juego.
- **Deceleración de plan de estación por vehículo (2026-10-18).** En el M3A los escalones B1/B2/B3 del plan salen de ≈ 0,33-0,39 m/s² aprendidos (no tiene esas muescas), mientras las posiciones MC miden 0,5-0,6. Nuevo `physics.station_plan_decel_ms2` (M3A: 0,5; sin valor = comportamiento anterior, Class 323 intacta): el plan calcula el inicio de frenada con esa decel única y la posición MC la sigue eligiendo la tabla aprendida. Ganancia teórica en los últimos 300 m a 30 mph: 41,5 s → 35,8 s (≈ 6 s por parada); con 0,7 serían 31,9 s, pero las posiciones MC no lo sostienen. La simulación del plan real da 2-4 s por parada y algo más de cambios de posición. Sin validar en juego.
- **Paradas no repetibles.** La distancia que la app cree que queda al parar varía mucho entre
  sesiones (White Plains 54–118 m, Hartsdale 7–92 m). Un offset constante no lo arreglaría.
- **Base de datos.** `tsw_hud.db` tiene la Harlem Line (ruta 13, 303 tablones), pero los 4991
  registros de horario no tienen coordenadas ni tablón asignado. La re-extracción con `hud.exe`
  no lo corrige y deja `bound` vacío. Los tablones y el trazado del servicio sí existen. Pendiente:
  distancia a lo largo de la vía hasta el tablón, y elegir el tablón por sentido.
- **Aprendizaje de frenado.** Se corrigieron dos fallos: muestras con freno no aplicado
  (`not_braking`) y filtro de outliers demasiado estrecho (`decel_outlier`). Con ello pasó de 47 a
  84–107 muestras por sesión. Sigue sin aprenderse el tiempo de llenado (`brake_fill_n = 0`):
  `brake_cyl_bar` marca 10–11 bar siempre y no se comporta como presión de cilindro.
- **RELEASE en marcha.** `station_coast_release_in_motion` enviaba RELEASE a neutro cada 2 ticks
  con la palanca ya en neutro (63 envíos en Crestwood, 201122Z) y pisaba al maquinista. Ahora exige
  freno aplicado. Falta confirmarlo en una sesión nueva.
- **Ritmo de frenado.** Desde ~60 mph arranca a ~950–1050 m de la parada con decel media
  0,31–0,40 m/s² (71–81 s). Es conservador frente a un freno cómodo habitual (≈ 0,6–0,8 m/s²,
  sin dato propio del M3A). Subirlo se aplaza hasta resolver la distancia al tablón.

## 8. Orden sugerido de trabajo

1. ~~Unificar constantes de timeout~~ (hecho 2026-10-19).
2. ~~Unificar `PredictDecelFn`~~ (hecho).
3. Terminar los parámetros de física por vehículo (medir M3A) y escribir pruebas de contrato por vehículo (§2.4 pasos 1 y 4).
4. Revisar `except Exception` (riesgo de ocultar fallos).
5. Cerrar hueco ACK ok (lógica de control; requiere validación).
6. Decidir ventana de aprendizaje (diseño; requiere confirmación).
7. Adaptador de vehículo (§2.4 paso 2) con el modelo de palanca de §2.6, y registro de flotas por datos (paso 3).
8. Distancia al tablón a lo largo de la vía (§7), tras validar con sesión y capturas.
9. Partir `session_report.py` y reorganizar carpetas (refactor grande; hacerlo aparte y al final).
