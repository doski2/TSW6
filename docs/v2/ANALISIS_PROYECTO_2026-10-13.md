# Análisis del proyecto V2 — 2026-10-13 (actualizado 2026-10-23, cierre de sesión)

Alcance: `V2/tsw6v2/` (71 módulos incluido `bridge/`, ~19,9 k líneas; 48 ficheros de test, 635
pruebas, 4 saltadas; cifras del 2026-10-23).
Medido con un script AST el 2026-10-19 (tamaños, funciones largas, duplicados, código sin
referencias).
Evidencia clasificada según `00-tsw6-core.mdc`: FACT = código leído o medido en logs; INFERENCE =
deducción; UNKNOWN = no demostrado.

Cambios respecto a la versión del 2026-10-13: tamaños (§1), arquitectura multi-locomotora (§2),
hallazgos de las sesiones del 2026-10-15 (§7) y re-análisis del 2026-10-19: duplicados, código sin
uso, funciones largas y riesgos nuevos en §3–§5 (marcados «2026-10-19»). §9 resume lo hecho el
2026-10-19 y lo pendiente con prioridad.

Actualización 2026-10-23: §7 recoge los hallazgos de las sesiones `203644Z`, `205735Z` y
`212139Z` (2026-10-22) y §10.4 contrasta lo pendiente de §10.2 con esos logs. Inventario de trenes del DLC en [TRENES_DLC.md](TRENES_DLC.md).

**Cierre de sesión 2026-10-23 (lo hecho, todo en commits, árbol limpio):** `decision.py` partido
en 7 módulos (1362 → 238 líneas; pasos 5 y 6 de [DECISION_MODULOS.md](DECISION_MODULOS.md)), con la
lógica MC y el bleed de andén detrás de `vehicle_adapter`; `load_ticks` unificado
(`session_io.py`); pruebas propias de `control_lock`, `service_brake`, `limit_containment` y
`autopilot_limit`. Todo refactor sin cambio de comportamiento (paridad medida: 56 797 ticks de las
sesiones del 22-oct, decisiones idénticas). **Lo que queda necesita sesión de juego o decisión de
diseño. Empezar la próxima sesión por §10.5.**

## 1. Tamaño y complejidad (FACT)

Archivos más grandes (líneas):

| Líneas | Archivo              | Nota                                                    |
| ------ | -------------------- | ------------------------------------------------------- |
| 1678   | `session_report.py`  | HTML + cálculo; candidato a partir (render vs métricas) |
| 238    | `decision.py`        | Orquestador P1 tras partirlo (2026-10-23; era 1362): `decision_types` 189, `decision_prep` 121, `decision_emergency` 143, `decision_release` 366, `decision_mc` 163, `decision_targets` 159, `decision_finalize` 191 |
| 1037   | `loop.py`            | Bucle agente; envío IPC + estado                        |
| 1026   | `p1_station_gate.py` | FSM de estación                                         |
| 1062   | `vehicle_package.py` | Datos de vehículo (19 helpers `mc_*`)                   |
| 828    | `station_plan.py`    | Perfil de parada en andén                               |
| 806    | `command.py`         | `BrakeCommand` y mandos IPC                             |
| 794    | `gui.py`             |                                                         |
| 654    | `physics.py`         | También lo importa el paquete v1 `tsw6/governor`        |
| 541    | `planning_poller.py` |                                                         |

Funciones más largas (2026-10-19, salvo la marcada; ≥ 120 líneas son candidatas a partir): `loop._step_core` 346,
`session_report._render_chart_svg` 322, `session_report.write_html_replay` 290,
`decision.evaluate_p1_tick` 184 (era 287), `diagnostic.run_ipc_brake_test` 165, `loop.from_probe` 161,
`cli.main` 161, `gui._build_ui` 135, `limits._evaluate_next_limit_brake` 131,
`session_report.summarize` 130, `cli.run_console` 122.

## 2. ¿Separar por locomotora? Arquitectura multi-vehículo

Pregunta: hoy hay 2 vehículos (Class 323 y M3A) y faltan muchos más. ¿El código actual servirá
para todos y conviene separar ficheros?

### 2.1 Estado actual (FACT)

- Hay **dos paquetes de vehículo** en `data/vehicles/`: `class_323.json` (layout muesca combinada

  UK) y `m3a_mnr.json` (layout `combined` con palanca MC analógica). No hay ningún otro.

- La bifurcación entre ambos estaba **dispersa** (36 puntos con `uses_mc_analog_ipc`, 20 fuera de

  `vehicle_package.py`). Desde el 2026-10-19 todos pasan por `vehicle_adapter.py`
  (`adapter_for_package(pkg)`); ver §8 punto 7.

- Solo hay **dos modelos de aire**: `uk_emu` y `master_controller` (`brake_air_profile.py`).
- La región ya se lee del campo `fleet` del paquete (2026-10-19). Solo sin paquete cae a cadenas

  fijas (`NYH`/`_MNR_` → `ny`; `BCC`/`CLASS323` → `uk`; otro → `None`, se confía sin validar).

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

  `p1_station_gate.py`, `command.py`, `ipc.py`) para añadir otra rama `if`. Hoy el adaptador
centraliza la decisión y (desde el 2026-10-23) también la lógica MC de parada, cartel y bleed de
andén; lo que sigue dentro de esos archivos son las guardas `analog_lever` y las constantes UK.

- Un arreglo pensado para la M3A puede romper la 323 sin que lo detecte un test: 21 de los 40

ficheros de test mencionan 323 o M3A, y desde el 2026-10-19 hay un conjunto común
(`test_vehicle_contract.py`,
  `test_vehicle_adapter.py`), aunque no cubre aún parada en andén ni soltar al salir.

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

- **Alias `DEFAULT_ACK_TIMEOUT_S`** (2026-10-19): el de `loop.py` se eliminó (usa

  `AGENT_ACK_TIMEOUT_S`).
  Queda el de `ipc.py`, que es el nombre público de sus defaults; mismo valor, sin acción.

- **Resuelto (2026-10-23): `load_ticks`.** Ambos módulos usan `session_io.iter_session_rows(path,
  strict=...)`: estricto en el informe (línea rota → `ValueError`), tolerante en el análisis OCR.
  Pruebas en `test_session_io.py`. Descripción original:
- **`load_ticks` en 2 módulos** (2026-10-19): `hud_ocr_eval.py` (lista de ticks, ignora líneas

  rotas)
y `session_report.py` (devuelve sesión + ticks, falla con una línea rota). Mismo formato JSONL, dos
  lectores. Unificar en un lector de JSONL de sesión con política de errores explícita.

- **Sin cuerpos de función duplicados** (2026-10-19): comparación de AST de todas las funciones con

  ≥ 3 sentencias, sin coincidencias.

- **`main` en 2 módulos**: normal (puntos de entrada), sin acción.

### 3.1 Código sin referencias (2026-10-19, FACT: sin usos en `tsw6v2`, tests ni scripts)

**Borradas el 2026-10-19** (569 pruebas en verde): `gui_view.layer_catalog`, `hud_db.is_same_stop`,
`physics.active_station_plan_decel`, `physics.low_speed_reaction_scale`,
`physics.is_in_brake_action_window` (solo se citaba en `docs/v1/`) y
`vehicle_package.session_route_hint_for_probe`.

**Se dejan:** `diagnostic_mc_ipc.run_mc_analog_ipc_test` (el módulo entero queda sin punto de
entrada;
decidir si es una herramienta de laboratorio que se quiere conservar).

**No borrar** `physics.should_brake_for_target` ni sus vecinas sin mirar: `tsw6/governor/` (paquete
v1)
las importa de `tsw6v2.physics`. El paquete v1 depende de V2, no al revés.

### 3.2 Módulos sin ninguna referencia en tests (2026-10-19; actualizado 2026-10-23)

**Cubiertos el 2026-10-23** con pruebas propias: `control_lock` (mutex con nombre único, para no
chocar con una GUI abierta), `service_brake`, `limit_containment` y `autopilot_limit`.
`diag_station` se borró. **Siguen sin pruebas propias:** `cli` y `diagnostic_mc_ipc` (este último,
además, sin punto de entrada; ver §3.1).

## 4. Fallos y riesgos (FACT salvo indicado)

- **ACK ok sin confirmar palanca** (`loop.py`, `_notch_step_pending`): si el ACK es `ok` el

  pendiente no se activa, y el paso puede reenviarse si la palanca tarda en cambiar. Hueco conocido,
  bajo riesgo observado (5 cambios de palanca en 1547 ticks en 214529Z).

- **Excepciones amplias** (`except Exception`): resuelto en `hud_schedule.py` (ver §8 punto 4).

  Quedan
  5 deliberadas: `cli.py:165`, `hud_ocr.py:149,292,299` y `planning_poller.py:447` (hilos y
  utilidades que no deben morir; registran el error).

- **Ventana de aprendizaje de 2 s** (`learn_quality.py`): cualquier cambio de muesca descarta la

  ventana entera (`notch_unstable`). Limita el aprendizaje de `mixed` (87 rechazos en 201122Z).
  Cambio de diseño pendiente de confirmación.

- **Texto corrupto (mojibake) en `loop.py`** (2026-10-19, corregido): 14 líneas de comentarios y

  docstrings con doble codificación (`Ã©`, `â†’`), introducidas en el commit `53a3ac4`. Se repararon
  recodificando; comprobar con `grep -P "â€|Ã.|â†"` que no reaparecen.

- **Finales de línea mezclados** (2026-10-19): `command.py`, `hud_ocr.py`, `learner.py`, `loop.py`,

  `station_plan.py` y `trace.py` están en CRLF; el resto en LF, y `.gitattributes` solo fija `.bat`.
  Cualquier script que reescriba un fichero puede convertirlo entero y generar un diff de miles de
líneas (ocurrió con tres módulos durante este trabajo). **Resuelto el 2026-10-19:** `.gitattributes`
  fija `*.py text eol=lf` y los seis módulos se pasaron a LF. Conviene hacer el commit de esa
  normalización aparte del resto, porque el diff de esos seis ficheros es casi total.

- **ACK ok sin pendiente, confirmado en código** (2026-10-19, `loop.py` ≈ l. 985): el comentario

  dice
«pendiente hasta que la palanca cambie o el ACK sea ok», pero con ACK ok se pone `None`, de modo que
  el paso se reenvía si la palanca tarda en cambiar.

- **Funciones demasiado largas** (§1): `loop._step_core` (346 líneas) concentra la mayor parte del
  control; `decision.evaluate_p1_tick` bajó de 287 a 184 tras partir sus fases (2026-10-23).
  Cualquier cambio en `_step_core` es difícil de revisar y de probar por separado.

- **Rama MC y rama combinada** comparten `_brake_kind`/aprendizaje pero con tablas distintas; el

  riesgo es confusión de tablas (ya tratado con `brake_kind` explícito).

## 5. Mejoras propuestas (INFERENCE)

1. ~~Unificar timeouts de ACK~~ y 2. ~~`PredictDecelFn` única~~: hechos (ver §3).
2. ~~Sustituir los `except Exception`~~: hecho donde procedía (§8 punto 4).
3. Partir `session_report.py` en: métricas (sin HTML) y render HTML.
4. Confirmar la ventana de 2 s: reiniciar solo desde el último tick válido en lugar de borrar todo.
5. Cerrar el hueco del ACK ok: marcar pendiente también con ACK ok hasta que la palanca confirme el

   cambio.

6. Parámetros por vehículo y adaptador de vehículo (ver §2.4).
7. ~~Normalizar finales de línea~~ (hecho 2026-10-19).
8. ~~Borrar el código sin referencias de §3.1~~ y ~~el alias de `loop.py`~~ (hecho 2026-10-19);

   `load_ticks` unificado el 2026-10-23.

9. (2026-10-19) Partir `loop._step_core` en pasos con nombre (leer sensores, decidir, enviar IPC,
    registrar), con las pruebas actuales como red. `evaluate_p1_tick` ya está partido (2026-10-23).

10. ~~Pruebas propias para `control_lock`, `service_brake`, `limit_containment` y `autopilot_limit`~~
    (hecho 2026-10-23). Pendiente: ampliar el contrato por vehículo con parada en andén y soltar al
    salir.

## 6. Pendiente de validación (UNKNOWN)

- Efecto real del pendiente de paso sobre la palanca en campo (solo 1 sesión evaluada).
- Si `v1_mixed` converge con varias sesiones limpias.
- Regla de 300 m de llegada/DEPARTING: sin segunda parada en campo.
- Comportamiento con un tercer vehículo (ver §2.5).

## 7. Hallazgos de las sesiones del 2026-10-15 (FACT salvo indicado)

Logs `20261015T184644Z` a `20261015T210604Z`, ruta `gct-mnr`, M3A.

- **Distancia a la estación.** `distanceToStationCM` de `DriverAid.TrackData` es el **fin del

  andén**,
  no el tablón de parada (`docs/reference/DRIVERAID_API.md:222`). Medido contra el HUD del juego:
  White Plains 15,5 m (HUD) frente a 133,4 m (app); Hartsdale ≈ 447 m frente a 481 m. El desfase
  cambia por estación (≈ 35 a ≈ 118 m), así que no es una constante ni solo el retardo HTTP.

- **Retardo HTTP.** La lectura de `TrackData` cambia cada 4,2 s de mediana (mínimo 3,9 s; la doc

  decía ~2 s). Se añadió `PLANNING_HTTP_LAG_S = 2.0` y `compensate_http_distance_m`
  (`planning_feed.py`). Efecto en campo: UNKNOWN.

- **OCR del HUD (medición, 2026-10-18).** El OCR se había descartado como control (`PLAN_V2` §4.4).

  Se añadió como medición: `--hud-ocr` graba `hud_ocr_m` en el JSONL y `scripts/analyze_hud_ocr.py`
  evalúa «corregir cada N capturas». Ver [HUD_OCR_MEDICION.md](HUD_OCR_MEDICION.md). Resultado en
  campo: UNKNOWN.

- **Dead-reckoning con límite de fps (2026-10-18).** Con el juego limitado a 50 fps el probe escribe

  un `seq` cada 60 ms (16,67 Hz), no cada 50 ms. Convertir `seq×50 ms` hacía avanzar la distancia ≈
  20 % de menos entre lecturas HTTP y dejaba plana la distancia en el 17 % de los ticks (micro
  paradas). Ahora el `dt` sale del reloj de pared y el `seq` solo detecta pausa (`PROBE_FROZEN_S`) o
  retroceso (`resolve_station_tick_dt`). Sin validar en juego. `active_t_ms` del informe sigue
  usando `seq×50 ms`. Diagnóstico de fluidez: `perf_ms` en el JSONL.

- **Parada corta y rodar en la aproximación final (2026-10-18, 181008Z).** Tres paradas de ocho

  quedaron 42-58 m antes del tablón: el clic del M3A frena ≈ 0,34 m/s² y desde 13 mph a 100 m bastan
  ≈ 0,17. El corte «no rodar con la parada en curso a < 100 m» (090737Z) lo impedía. Ahora
  `mc_station_roll_allowed` no corta por distancia, la banda de histéresis es proporcional (10 % de
  la distancia, 2-20 m) y `StationRollLatch` exige 3 s entre conmutaciones rodar↔frenar (simulado:
  parada a ≈ 6 m corto con 4-8 conmutaciones). Sin validar en juego. También: con el ancla HUD
  «stn≤1 m» es llegada al tablón, no marcador pasado (`MARKER_PASSED_MIN_MPH_BOARD`); causó la
  emergencia de Fleetwood.

- **Parada en estación fuera del horario (2026-10-18, 203040Z).** El servicio 500 no para en Tremont

  (horario de la BD: Fordham 05:27:00 → Harlem 125th 05:34:30). Dos causas: `PlayerInfo` fallaba de
  forma intermitente y el poll caía a `track_only` (sin filtro de horario; 50 298 ticks `hud_db`
  frente a 5 183 `track_only`), y si ninguna parada programada salía aún en `TrackData`,
  `apply_station_schedule` devolvía todas las estaciones. Ahora el poll usa el último servicio
  conocido (`service_name_hint`) y, tras cruzar alguna vez horario y `TrackData`, no ofrece
  estaciones no programadas (`fallback_all_when_unmatched`). Sin validar en juego.

- **Deceleración de plan de estación por vehículo (2026-10-18).** En el M3A los escalones B1/B2/B3

  del plan salen de ≈ 0,33-0,39 m/s² aprendidos (no tiene esas muescas), mientras las posiciones MC
  miden 0,5-0,6. Nuevo `physics.station_plan_decel_ms2` (M3A: 0,5; sin valor = comportamiento
  anterior, Class 323 intacta): el plan calcula el inicio de frenada con esa decel única y la
  posición MC la sigue eligiendo la tabla aprendida. Ganancia teórica en los últimos 300 m a 30 mph:
  41,5 s → 35,8 s (≈ 6 s por parada); con 0,7 serían 31,9 s, pero las posiciones MC no lo sostienen.
  La simulación del plan real da 2-4 s por parada y algo más de cambios de posición. Sin validar en
  juego.

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

- **Frenada en vía abierta por lectura OCR rota (2026-10-21, `20261020T211925Z`, M3A, servicio

  500).**
  Tras salir de Fordham (último andén programado) el planificador no ofrecía ya ningún andén
  (`regress_moving@3`, 190 rechazos) y la distancia salía solo del ancla HUD, que leía «4,0mi
  Harlem 125th» (6437 m). En t = 2755 s el OCR devolvió «39m» (era «3,9mi»: perdió la coma y la `i`)
  y tres capturas iguales bastaron para un `resync` de −6398 m (`HudAnchor._gated`). Con 64 mph y
  «tablón a 34,5 m» P1 emitió `P1-CRITICO-STATION` (APPLY B3, palanca 0) y el tren paró en vía, sin
  andén. Repitió a los 28 s: la distancia quedó congelada en 35,5 m aunque el tren volvió a 31 mph.
  Corrección (2026-10-21, sin validar en juego): `hud_anchor.py` descarta capturas que no sean
continuas con la anterior avanzada a la velocidad actual (`jump`, holgura 250 m o 25 %) y el resync
  no acepta saltos mayores de 1000 m (`resync_too_far`); 3 pruebas nuevas en `test_hud_anchor.py`.
Segunda guarda (2026-10-21): con la estimación ya en el andén servido (≤ 20 m) una captura no puede
  subirla más de 150 m (`departed`); es lo que impedía que el HUD, apuntando a Harlem 125th a 7 km,
  creara una distancia de estación fantasma justo después de salir de Fordham. **Repetición sobre el
  log real** (ancla alimentada con las lecturas de `hud_ocr_m` desde la salida de Fordham, 495
  capturas): 345 rechazadas por `departed`, 150 por `jump`, 0 movimientos de la distancia; antes del
  cambio la distancia pasaba de 0 a 7078 m y luego a 34,5 m. Sin validar en juego.
  Cubierto por estas guardas: la unidad mal leída (a), el salto/congelado (c) y la estación fantasma
tras el último andén (d). Pendiente solo (b), defensa en profundidad: no emitir `P1-CRITICO-STATION`
  a alta velocidad si la distancia procede del ancla y acaba de saltar.

### 7.1 Sesiones del 2026-10-22 (`203644Z`, `205735Z`, `212139Z`; M3A, servicio 500, `gct-mnr`)

Medido sobre los JSONL (FACT). Las dos primeras corren con el commit `e36daa6`; la tercera con
`40c3ec6` (ya con las correcciones a) y b) de abajo).

- **a) Parpadeo APPLY/RELEASE al aproximar el cartel de 35** (`203644Z`, t = 432 s, 40,4 mph, 186 m).
  17 ticks seguidos alternando `APPLY B1` y `RELEASE «Objetivo alcanzado»`; el tren casi no frenó
  (40,39 → 40,18 mph). Causa: `resolve_orphan_limit_brake_release` usaba
  `within_next_brake_horizon` (169 m) mientras el plan ya aplicaba a 186 m; fuera del horizonte
  soltaba el freno recién aplicado (reproducido con los valores del log). Corrección `29ff979`: la
  liberación huérfana respeta la muesca comprometida (`committed_limit_mph`). Sin validar en juego.
- **b) Frenada en vía abierta por «3,0 mi» leído «30m»** (`205735Z`, t = 997 s, 71 mph). Mismo
  fallo que 211925Z: pasados 15 s sin lectura coherente el ancla pierde la referencia
  (`CONTINUITY_MAX_AGE_S`) y aceptó 30 m; `departed` no lo paró (30 m no sube 150 m sobre 0). Dio
  `P1-EMERGENCIA-STATION` (523 ticks) y el tren paró a 2,7 mi de Harlem 125th. Corrección
  `40c3ec6`: `parse_hud_distance` descarta la unidad `m` suelta (el HUD imperial solo muestra `ft`
  o `mi`) salvo `TSW6_HUD_OCR_METERS=1`. En `212139Z` hubo 5 muestras `Nm lem…` y ninguna entró.
- **c) Frenada al 100 % a 65-72 mph** (`212139Z`, t = 235 s, 71,6 mph, cartel 60 a 596 m). El plan
  existía (B1 bastaba con 64 m de margen) pero la rama de overspeed de `apply_notch_hysteresis`
  escalaba una muesca por tick (B1→B2→B3 en 3 ticks) porque lejos del cartel la velocidad siempre
  supera el objetivo. El eje llegó a 0,27 (freno pleno) y el tren acabó a 57,6 mph, bajo los 59.
  Corrección `ebc13dd`: solo escala si la muesca comprometida no llega al objetivo
  (`_committed_notch_reaches_target`). Sin validar en juego.
- **d) Cartel con eje analógico (M3A), commit `3942dde`.** `mc_limit_brake_fraction` +
  `decision_mc.mc_limit_fraction` (antes `decision._mc_limit_fraction`): la posición del eje sale de la decel necesaria sobre la curva
  aprendida `decel_by_mc`, no del peldaño B1/B2/B3. Envolvente monótona conservadora
  (`_monotone_decel_table`) porque la curva es ruidosa (0,60 → 0,29 y 0,62 → 0,38 m/s²); también
  afecta a la parada en andén. La 323 conserva las muescas. Sin validar en juego.
- **e) Parpadeo persistente en la banda del límite (NUEVO, abierto).** En `212139Z` hay 199
  alternancias APPLY↔RELEASE en 29 racimos. El mayor: zona de 10 mph hacia Grand Central
  (t = 871-925 s): con la velocidad clavada en 9,26 mph y objetivo `@9`, `APPLY B1` / `RELEASE`
  cada tick, 10-41 ticks por racimo, unas 15 veces. Causa probable (INFERENCE): umbrales
  invertidos entre el plan (aplica si v > objetivo) y `resolve_release_command` (suelta si
  v ≤ objetivo + `LIMIT_RELEASE_MAX_OVER_MPH` = 0,4); en [9,0; 9,4] ambos se cumplen y alternan. La
  guarda de (a) cubre solo la rama huérfana, no esta. **Corregido 2026-10-23 (commit `c449f7b`, sin validar en
  juego):** `decision_release._limit_plan_owns_brake` — con el plan del cartel en `apply_now` y la
  velocidad por encima de su objetivo no se suelta por la banda de `resolve_release_command`.
  Reproducido en el replay (`evaluate_p1_tick` con el `lever` del tick anterior: el `lever` del JSONL
  es el estado tras el mando) y regresión en `test_release.py`. Sobre las tres sesiones completas
  (56 797 ticks) solo cambian 62 ticks, todos de `212139Z` y todos `release/RELEASE` →
  `plan/APPLY`. El parpadeo de aproximación a andén (`Estación dist=43/32/20/10 m`) NO es este
  fallo: es la histéresis rodar↔frenar de `StationRollLatch` (3 s) y queda como está. Parpadeo análogo en la aproximación a andén
  (`Estación dist=43/32/20/10 m`, t = 1245-1257 s) y en `203644Z` (White Plains).
- **f) Paradas contra el HUD** (última lectura OCR válida con el tren parado): 7,0 / 2,1 m
  (`203644Z`); 2,1 / 1,8 / 1,8 / 1,5 / 1,5 / 1,5 m (`205735Z`); 2,1 / 3,0 / 7,9 m (`212139Z`). Todas
  quedan cortas 1,5-8 m del tablón; ninguna se pasa. La app cree estar a 0,0-8,7 m (`stn_dist_m`).
- **g) Tras el último andén** (`212139Z`): Fordham (79 s) → Harlem 125th (534 s) sin emergencias,
  5239 capturas `departed` y 290 `jump` rechazadas, 0 movimientos de distancia.

### 7.2 Sesión del 2026-10-23 (`20261023T201351Z`; M3A, servicio 2307, `gct-mnr`)

Servicio 2307: 05:56, 26 min, northbound, **una sola parada: Crestwood vía 4 (06:22)**, según
`tsw_hud.db` (timetable 18612). Log de 581 s (la sesión seguía abierta). Commit de partida `60c6019`.

- **Frenada para una estación que no es parada (FACT, corregido, sin validar en juego).** Los 11 425
  ticks salen con `schedule_source = track_only`; el agente seguía «Harlem 125th Street, vía 3» y al
  final aplicaba `APPLY` para pararse a 124-163 m de ella, mientras el HUD del juego apuntaba a
  «Deténgase en el lugar — Crestwood, vía 4 — 12 mi» (captura 22:23). Causa: la BD resuelve bien el
  servicio (`resolve_hud_service_stops('2307')` → `['Crestwood']`), pero Crestwood está a ~19 km y no
  sale aún en `TrackData`; `apply_station_schedule` caía entonces al respaldo «todas las estaciones»
  porque `fallback_all_when_unmatched` sigue activo hasta el primer match (arreglo de 203040Z, que
  solo cubría el caso ya cruzado). Corrección: `hud_schedule.scheduled_stops_beyond_trackdata` — si
  la posición del jugador (`PlayerInfo.geoLocation`) está a más de 3 km de TODAS las paradas del
  horario con coordenadas en la BD, no se ofrece ninguna estación (`hud_db`, lista vacía), con
  independencia del respaldo. Con la parada a < 3 km, o sin posición / coordenadas, se mantiene el
  respaldo por si los nombres no cuadran. 3 pruebas nuevas en `test_hud_schedule.py` (627 en total).
  **Por validar:** que `PlayerInfo` entregue `geoLocation` en juego (la doc lo marca ✅; no hay
  lectura en el JSONL) y que Crestwood sí aparezca en `TrackData` al acercarse.
- **OCR a distancia larga (FACT).** `hud_ocr_diag`: 115 muestras; 0 `hits` hasta t = 323 s. El HUD
  muestra millas enteras con la distancia larga («16 mi», «12 mi»). Lecturas: `16mi` y `16m` (sin
  parsear: > 20 km o unidad `m` suelta), **`5mi` ← «15 mi» y `3mi` ← «13 mi» (se pierde el primer
  dígito y SÍ parsean: 8,0 y 4,8 km en lugar de 24 y 21 km)**, `13.mi` (no parsea), `12mi` → 19 312 m
  (correcta). El ancla (`ocr_anchor`) quedó en `wait` / `frame_gate` / `jump` toda la sesión: no
  intervino, y a esa distancia no debe. Pendiente (defensa en profundidad, **no implementado**): si el
  OCR da de forma estable una distancia lejana (≥ 2 km) mientras el HTTP da una estación a < 1 km,
  la estación HTTP no es el objetivo del HUD → no frenar para ella. Habría cubierto este fallo aun
  con el horario mal resuelto.

### 7.3 Sesión del 2026-10-23 (`20261023T203255Z`; M3A, servicio 2307, 133 s)

Mismo servicio que 7.2, ya con la corrección del horario (`schedule_source = hud_db` en 2499 de
2645 ticks: durante los primeros 24 s no hubo estación, como debe ser).

- **Freno sin soltar hasta casi 0 mph (FACT, corregido, sin validar en juego).** A 106,5 s (10,3 mph,
  zona de 10 mph en bajada) el agente aplicó `APPLY B1` por «Mantener bajada @10.3». La velocidad
  cayó a 1,4 mph (regeneración hasta −200 A) y **no soltó hasta 122,7 s**. Causa: una **estación
  fantasma** («Grand Central, vía 28», `stn_dist_m` congelada en 198,3 m durante ~1900 ticks) que
  bloquea los caminos de soltar. Repetido con `evaluate_p1_tick` sobre el log: con la estación
  logueada 0 `RELEASE` entre 107 y 122,5 s; sin ella, 302 ticks `release` desde 108 s. Origen de la
  estación: a 24,6 s un poll llegó como `track_only` (sin filtro de horario) y aceptó Grand Central a
  242 m; cuando volvió `hud_db` con la lista vacía, **la estación guardada no se borró** (el poll
  salía antes de tocar la distancia) y `_reading_stale` la congeló. Corrección en
  `planning_poller`: (1) `_hud_db_seen` — tras resolver el servicio por la BD se ignoran las lecturas
  `track_only`; (2) `_drop_station_reading` — con `hud_db`, `stations` vacío y sin `next_stop` se
  olvida la estación guardada. 3 pruebas nuevas en `test_planning_poller.py` (630 en total).
  **Por validar:** que el 2307 completo no ofrezca Grand Central ni Harlem 125th. **Sigue abierto:**
  por qué ese poll llegó como `track_only` (PlayerInfo / BD intermitente; no queda rastro en el
  JSONL) y, en profundidad, que una distancia congelada con el tren en marcha caduque en lugar de
  bloquear el soltar.
- **Mandos IPC repetidos (FACT, hueco ya conocido de §4).** 16 mandos en 133 s: 14 `RELEASE NEU` y 2
  `APPLY B1`; **13 de 16 repiten el mando anterior a menos de 1 s** (11 `RELEASE` en 0,7 s al
  arrancar, mientras la palanca va de 0,32 a 0,72; ids 1-11 todos con ACK `ok`). En
  `20261023T201351Z`: 75 de 138. Es el «ACK ok sin pendiente» de §4: con ACK `ok` no se marca
  pendiente y el paso se reenvía cada tick hasta que la palanca confirma. Inofensivo en lo medido
  (todos `ok`, mismo destino) pero ruido en el bus y en el informe. Prioridad subida: ahora hay
  medición.
- **Ticks con el mismo `seq` (no es un fallo):** 492 de 2645 filas (19 %) repiten el `seq` del probe
  (el agente corre a ~20 Hz y el probe escribe a 16,7 Hz con el juego a 50 fps; ver §7, dead-
  reckoning). No hay `tick` duplicados ni filas repetidas. El log tiene 4 filas `session_detect`
  (actualizaciones de servicio / horario), normal.

### 7.4 Primera sesión de la Class 323 (`20261023T211407Z`; cabina `DMS_B_C`, servicio 2O02, `cross-city`, 544 s)

Commit de partida `7d0a732`. Dos paradas, **las dos cortas: Sutton Coldfield a 45,4 m y Wylde Green a
63,3 m del tablón** (la app cree estar a esa distancia al parar; ancla HUD `board off=130`). Causas
(FACT, medidas sobre el JSONL), todas corregidas **sin validar en juego**:

- **El paquete de la 323 no resolvía para la cabina B.** `class_323.json` declaraba
  `match.vehicle_class = RVM_BCC_WRM_Class323_DMS_A_C` y `vehicle_class_matches` es exacto o por
  prefijo; la sesión corrió con `DMS_B_C` → `resolve_vehicle_package` = `None`: sin bloque `physics`,
  sin perfil de aire, `NotchAdapter(None)`. El M3A ya usaba el prefijo corto (`RVM_NYH_MNR_M3a`).
  Corrección: `match.vehicle_class = RVM_BCC_WRM_Class323_DMS`.
- **B1 real ≈ 0,5-0,7 m/s², el plan usa 0,35.** Cuatro ventanas con la palanca en B1 estable (sin los
  primeros 2,5 s de llenado): 0,51 (42→36 mph, −1 %), 0,50 (33→24 mph, −1 %), 0,69 (15→1 mph, llano),
  0,58 (22→1 mph); decel efectiva de las dos frenadas finales incluyendo el llenado: 0,75 (B1+B2) y
  0,57 (B1). Con 0,35 el plan frena demasiado pronto y demasiado fuerte → 45 y 63 m cortos (21 mph a
  110 m: 0,42 m/s² bastaban). Corrección en `class_323.json`: `service_decel_frac` B1 0,33 → **0,51**
  (0,55 m/s², algo por debajo de lo medido para fallar por corto y no por largo); B2 0,55 → 0,70 **solo
  para mantener B1 < B2 < B3, sin medir**; B3 sin cambios, sin medir (hay una ventana de 0,8 s a
  0,70 m/s²). **Ojo:** el aprendiz usa su EMA por muesca antes que las constantes de física
  (`_predict_for_kind`: `_by_notch > 0,05`). El perfil de esta sesión (B1 = −0,35, n = 35) se aprendió
  durante el ping-pong y se apartó a `logs/profiles/rvm_bcc_wrm_class323_dms_b_c.json.bak-20261023-
  contaminado`. **No se ha tocado** `RVM_BCC_WRM_Class323_DMS_A_C.json` (B1 −0,38 con n = 999,
  B2 −0,83, B3 −1,02): el aprendizaje histórico y la medición de hoy no cuadran; revisar cómo se
  mide la decel en la ventana de aprendizaje (¿incluye el llenado?).
- **Ping-pong `APPLY B1` ↔ `RELEASE «Objetivo alcanzado»` (485-510 s, 26 pares, palanca 3↔4).** El
  plan de estación aplicaba; en el tick siguiente (palanca ya en freno) el objetivo de estación
  desaparecía o se aplazaba y el camino de soltar por el cartel («objetivo alcanzado») lo deshacía.
  Mismo patrón que §7.1 e, ahora con objetivo de estación y sin cubrir por `_limit_plan_owns_brake`.
  Corrección: `decision_finalize` fija `limit_state.station_stop_m` también en el layout por muescas
  cuando el plan de estación manda `APPLY` (el analógico ya lo hacía), y `_limit_release_ok` /
  `station_stop_running` lo respetan. Efecto: el freno de la parada en curso es del plan de estación
  hasta que acaba (velocidad ≤ 1 mph o la estación sube > 20 m). Replay del log: pares 6 → 0.
- **Espera por aire (104 ticks `air_fill` / `air_recharge`, todos entre 480 y 540 s).** Nuevo flag de
  paquete `brake_air.gate_apply` (por defecto `true`); la 323 lo lleva a `false` y `BrakeAirTracker`
  deja de bloquear `air_ready` / `inhibit_reapply`. Mercancías u otros vehículos conservan el
  bloqueo. Sigue activo el tope de escalada de `cap_escalation` y el tiempo de llenado
  (`brake_fill_s`), que son físicos.
- **Soltar en marcha a 420 m (`platform_bleed_release`, 227,8 s, 23 mph).** `station_coast_release_in_
  motion` creyó que la inercia bastaba (coast 0,095 m/s²) y el tren **aceleró** de 21,9 a 24,0 mph en
  bajada (−1 %) durante 30 s antes de frenar tarde. Con la propiedad del freno ya no se dispara
  mientras la parada está en curso. **Sigue abierto:** el modelo de coast ignora la pendiente.

Comprobaciones: paridad de la M3A idéntica (56 797 ticks, mismo md5); 635 pruebas; la regresión
`test_class323_station_approach.py` (fixture de 485 ticks de la sesión) falla sin la corrección del
ping-pong y pasa con ella. **Por validar:** que la 323 pare cerca del tablón con B1 = 0,55; que no
vuelvan las alternancias; que el aprendizaje nuevo converja (con el perfil B limpio); B2 / B3.

## 8. Orden sugerido de trabajo

1. ~~Unificar constantes de timeout~~ (hecho 2026-10-19).
2. ~~Unificar `PredictDecelFn`~~ (hecho).
3. Terminar los parámetros de física por vehículo (medir M3A; pendiente, requiere sesión de juego).

   ~~Pruebas de contrato por vehículo~~ (hecho 2026-10-19: `V2/tests/test_vehicle_contract.py`,
   parametrizado con cada JSON de `data/vehicles/`: cabecera, resolución por clase, perfil de aire,
   física, valor IPC por muesca y `target_fraction` en layout MC; un vehículo nuevo debe pasarlas).

4. ~~Revisar `except Exception`~~ (hecho 2026-10-19: `hud_schedule.py` con excepciones concretas;

   `planning_poller.py` mantiene la captura amplia para no matar el hilo, pero registra a nivel
   warning con el tipo).

5. Cerrar hueco ACK ok (lógica de control; requiere validación).
6. Decidir ventana de aprendizaje (diseño; requiere confirmación).
7. Adaptador de vehículo (§2.4 paso 2) con el modelo de palanca de §2.6. *En curso (2026-10-19):*

   `vehicle_adapter.py` con `NotchAdapter` / `McAnalogAdapter` y siete miembros migrados
   (`throttle_notch`, `station_lever`, `lever_says_brake`, `single_step`, `wire_fraction`,
   `fraction_feedback`, `analog_lever`; `command.py`, `brake_cab.py`, `ipc.py` y `loop.py` delegan;
   `loop.py` ya no llama a `uses_mc_analog_ipc`). Ningún módulo fuera de `vehicle_package.py` y
   `vehicle_adapter.py` llama ya a `uses_mc_analog_ipc` (todos usan
   `adapter_for_package(...).analog_lever` u otra operación). *Hecho el 2026-10-23:* la lógica
   MC de parada, rodar hasta el clic y cartel (`station_stop_fraction`, `roll_until_click`,
   `limit_fraction`) y el bleed de andén (`bleed_b1_latched`, `bleed_neutral_reached`,
   `bleed_should_reapply_b1`) pasan por el adaptador; `NotchAdapter` devuelve `None`/`False`.
   Quedan las guardas `analog_lever` y el modelo de palanca de §2.6 (muescas UK). Registro de
   flotas por datos (paso 3): *hecho* — campo `fleet` en cada JSON, `vehicle_route_fleet` lo usa y
   cae al prefijo solo si no hay paquete.

8. Distancia al tablón a lo largo de la vía (§7), tras validar con sesión y capturas.
9. Partir `session_report.py` y reorganizar carpetas (refactor grande; hacerlo aparte y al final).

## 9. Resumen del 2026-10-19

Hecho (569 pruebas en verde, 4 saltadas): timeouts de ACK unificados; `PredictDecelFn` ya única;
`except Exception` revisados; pruebas de contrato por vehículo (`test_vehicle_contract.py`); campo
`fleet` en los paquetes; `vehicle_adapter.py` con pruebas propias (`test_vehicle_adapter.py`) y
ninguna llamada directa a `uses_mc_analog_ipc` fuera de `vehicle_package.py`; mojibake de `loop.py`
reparado.

Pendiente al 2026-10-19, con su estado a 2026-10-23:

1. Cerrar el hueco del ACK ok (§4) — control; validar en juego. **Sigue pendiente.**
2. ~~Finales de línea (§5.8)~~ y ~~código sin referencias (§3.1)~~: hechos y en commits.
3. ~~Unificar `load_ticks` (§3)~~ — hecho 2026-10-23.
4. ~~Pruebas de módulos sin cobertura propia (§3.2)~~ — hecho salvo `cli` y `diagnostic_mc_ipc`.
5. Partir `_step_core` / `evaluate_p1_tick` (§5.9): `evaluate_p1_tick` hecho; **queda `_step_core`**.
6. ~~Mover al adaptador la lógica de la M3A tras `analog_lever`~~ — hecho 2026-10-23 (§8 punto 7).
7. Medir la física real de la M3A (§2.4 paso 1) y la distancia al tablón (§7). **Sigue pendiente.**

## 10. Para cerrar la sesión: validar y tareas siguientes

### 10.1 Estado del árbol de trabajo

**Actualización 2026-10-23 (cierre de sesión): todo está en commits y el árbol está limpio.**
624 pruebas en verde, 4 saltadas. Commits de la sesión, en orden:

| Commit | Qué |
| ------ | --- |
| `c449f7b` | Partir `decision.py` (pasos 0-4: tipos, preparación, emergencia, soltar), borrar `diag_station`, y el cambio de lógica `_limit_plan_owns_brake` (parpadeo §7.1 e) |
| `6691cee` | Paso 5: `decision_mc.py` y operaciones MC / bleed en `vehicle_adapter` |
| `f1e8fb2` | Paso 6: `decision_targets.py` y `decision_finalize.py` |
| `559af85` | `load_ticks` unificado en `session_io.py` |
| `6764cb0` | Pruebas de `control_lock`, `service_brake`, `limit_containment`, `autopilot_limit` |

De ellos, **solo `c449f7b` contiene un cambio de comportamiento** (`_limit_plan_owns_brake`: 62 de
56 797 ticks); el resto son movimientos con paridad medida. Antes: `e24469f` … `ebc13dd` (adaptador,
ancla HUD, escalada en overspeed) y `3942dde` (eje analógico por cartel).

**Cómo se midió la paridad:** `V2/scripts/parity_jsonl.py <salida> <logs...>` vuelca por tick la
decisión de `evaluate_p1_tick` (comando, motivo, objetivo, fase, `apply_now`, distancia de andén y
`station_stop_m`). Se ejecuta antes y después de un refactor con los mismos logs y se compara con
`cmp`. Es lazo abierto y solo cubre la M3A (sin sesión de la 323).

### 10.2 Validar antes de dar por cerrado

Nada de esto lo cubren las pruebas automáticas; hace falta una sesión de juego:

| #   | Qué validar                                                                                                                                                                                                      | Cómo                                                                                                                | Vehículo        |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | --------------- |
| 1   | El refactor del adaptador no cambió el comportamiento: arranque, COAST, parada en andén, soltar al salir, RELEASE a neutro                                                                                       | Una sesión completa de 2-3 estaciones y comparar el JSONL con una sesión previa (decisiones, `lever`, IPC enviados) | M3A y Class 323 |
| 2   | `drive_to_notch` / `diagnostic` siguen mandando bien por IPC tras migrar `ipc.py`                                                                                                                                | `test_ipc_v2.bat` o `validar_freno.bat` con el probe activo                                                         | M3A y Class 323 |
| 3   | La 323 no se ha roto (solo hay pruebas unitarias para ella)                                                                                                                                                      | Ruta Cross-City, una parada                                                                                         | Class 323       |
| 4   | Punto del §7 aún sin validar en juego: dead-reckoning por reloj de pared, rodar en la aproximación final (`StationRollLatch`), filtro de horario (`fallback_all_when_unmatched`), `station_plan_decel_ms2` = 0,5 | Sesión gct-mnr, comparar paradas contra el HUD                                                                      | M3A             |
| 5   | RELEASE en marcha ya no se repite con la palanca en neutro                                                                                                                                                       | Buscar en el log RELEASE consecutivos con `lever` = neutro (63 en 201122Z)                                          | M3A             |
| 6   | Warning nuevo de `planning_poller` no inunda el log                                                                                                                                                              | Revisar el log de una sesión larga                                                                                  | cualquiera      |
| 7   | La continuidad del ancla HUD (`jump`) no descarta lecturas buenas: contar `jump` en el JSONL y comprobar que las paradas siguen ancladas (`board off=… n=…` sube)                                                | Sesión gct-mnr completa, buscar `jump` en `ocr_anchor`; debe aparecer solo en lecturas rotas                        | M3A             |
| 8   | Tras el último andén programado (Fordham → Harlem 125th) el tren no frena en vía                                                                                                                                 | Repetir el servicio 500 hasta pasar Fordham y circular ≥ 3 min                                                      | M3A             |

Criterio de aprobado para el punto 1: mismas decisiones y mismos mandos IPC que antes del refactor
en situaciones equivalentes. Si hay diferencias, el sospechoso son las guardas `analog_lever` de
`p1_station_gate.py`, `decision.py` y `loop.py` (la semántica con paquete `None` es la de la 323).

### 10.3 Tareas para las próximas sesiones (en orden)

0. **Validar la corrección de la frenada fantasma** (§7, 2026-10-21; filas 7 y 8 de §10.2) y, si se

   quiere defensa en profundidad, el punto (b).

1. ~~**Commits** del §10.1~~ (hechos 2026-10-23: son refactors con paridad medida; la validación
   1-3 sigue pendiente para los cambios de lógica).
2. **Hueco del ACK ok** (§4): marcar pendiente también con ACK ok hasta que la palanca confirme;

   test unitario del reenvío y validación en juego.

3. ~~**Unificar `load_ticks`**~~ (hecho 2026-10-23, `session_io.py`).
4. ~~**Pruebas propias** de `control_lock`, `service_brake`, `limit_containment`, `autopilot_limit`~~

   (hecho 2026-10-23, §3.2). Sigue pendiente ampliar el contrato por vehículo con parada en andén y soltar al salir.

5. **Decidir** si se conserva `diagnostic_mc_ipc` (§3.1).
6. **Medir la física de la M3A** (`physics` del JSON, hoy heredada de la 323) con una sesión de

   calibración de frenado.

7. **Partir** `loop._step_core` (`decision.py` ya está partido en 7 módulos y `evaluate_p1_tick`
   baja a 184 líneas; ver §10.5).
8. ~~**Mover al adaptador** la lógica de la M3A que sigue tras `analog_lever`~~ (hecho 2026-10-23).
   Sigue pendiente el modelo de palanca de §2.6 (decel objetivo → posición), tras validar en juego.
9. **Distancia al tablón** a lo largo de la vía (§7), tras validar con captura.
10. **Ventana de aprendizaje de 2 s** (§4): decisión de diseño pendiente.
11. Al final: partir `session_report.py` y reorganizar carpetas (§2.4 paso 5).

### 10.4 Validación contra los logs del 2026-10-22 (`203644Z`, `205735Z`, `212139Z`)

Contrasta la tabla de §10.2 con los JSONL posteriores a la última edición de este documento
(2026-10-22 22:32). Solo cuenta lo que los logs pueden demostrar.

| # §10.2 | Resultado | Evidencia |
| ------- | --------- | --------- |
| 1 Refactor del adaptador (M3A) | **Sin regresión visible** | 12 paradas en 3 sesiones, todas `STOPPED` cortas 1,5-8 m del tablón; arranque, COAST, andén y salida sin errores. Falta la comparación con la 323 y mando a mando contra una sesión previa |
| 2 `drive_to_notch` / `diagnostic` | **No evaluable** | Ninguna sesión lo ejercita; requiere `test_ipc_v2.bat` / `validar_freno.bat` |
| 3 Class 323 intacta | **No evaluable** | Las tres sesiones son M3A; sigue sin sesión de la 323 |
| 4 Dead-reckoning, rodar al final, filtro de horario, `station_plan_decel_ms2` | **Parcial** | `schedule_source` = `hud_db` en 99 % de los ticks (`212139Z`: 568 `track_only` de 26 118); sin paradas largas por horario. Paradas cortas del 10-18 no repetidas; el parpadeo de la aproximación a andén (§7.1 e) toca la zona de rodar↔frenar |
| 5 RELEASE en marcha con palanca en neutro | **Validado para DEPARTING** | 0 `RELEASE` con `lever` = 4 y FSM `DEPARTING` en las 3 sesiones (antes 63 en 201122Z). Los 101 / 1 / 212 `RELEASE` con neutro restantes son del parpadeo de §7.1 e, no de la salida |
| 6 Warning de `planning_poller` | **No evaluable** | El JSONL no registra el log de consola; revisar el `.log` de la sesión |
| 7 `jump` no descarta lecturas buenas | **Validado (con reserva)** | `212139Z`: `board` en 14 887 ticks, `jump` 290, `departed` 5239, las paradas siguen ancladas (`stn` 0,0-7,8). `205735Z` fue el contraejemplo del lado contrario (lectura rota aceptada tras 15 s) → corregido en `40c3ec6` |
| 8 Sin frenada en vía tras Fordham | **Validado en 1 sesión** | `212139Z`: Fordham → Harlem 125th sin emergencias. `205735Z` falló (con `e36daa6`) y motivó `40c3ec6`. Repetir al menos una vez más |

### 10.5 Para empezar la próxima sesión

**Estado de partida:** árbol limpio, 624 pruebas en verde (§10.1). Lo que queda ya no es
refactor mecánico: o necesita el juego o es un cambio de lógica que conviene hacer con validación.

**Regla para esta sesión:** no empezar cambios de lógica nuevos (punto 3) hasta haber validado los
de esta semana (punto 1). Si algo falla en juego con varios cambios sin validar, no se sabe qué
commit lo causó.

0. **Repetir el servicio 2307** — además de lo anterior, comprobar (§7.3) que no aparece ninguna
   estación fantasma (`stn_dist_m` congelada con el tren en marcha) y que el freno de bajada se
   suelta al caer bajo el objetivo. Antes, ver abajo el original:
0b. (original) **Repetir el servicio 2307** (o cualquier servicio de una parada lejana) con el commit que
   incluye `scheduled_stops_beyond_trackdata` (§7.2): comprobar que el agente no frena para Harlem
   125th, que `schedule_source` pasa a `hud_db` y que Crestwood aparece al acercarse. Si en el
   JSONL `stn_dist_m` sigue apuntando a Harlem, mirar si `PlayerInfo` entrega `geoLocation`.
1. **Sesión de la M3A en el juego** (servicio 500, `gct-mnr`, circular pasando Fordham ≥ 3 min). Con
   una sola sesión se validan (a)-(e) de §7.1:
   - cartel a 60-75 mph **sin escalada al 100 %** (el eje no debe llegar a 0,27 lejos del cartel);
   - **sin racimos** de alternancias APPLY↔RELEASE a 35 mph ni en la zona de 10 mph hacia Grand
     Central (contar en el JSONL);
   - ancla HUD **sin lecturas `Nm lem…`** y sin frenada en vía tras Fordham (fila 8 de §10.2);
   - eje continuo en el cartel (la curva `decel_by_mc` con pocos puntos puede caer al peldaño B3: a
     250 m, 72→59 mph la decel necesaria supera la curva).
   Después, repetir el análisis de §10.4 con los logs nuevos.
2. **Repetir la Class 323** (primera sesión hecha el 2026-10-23, §7.4; fila 3 de §10.2). Con los
   cambios de §7.4 (paquete para cabina A y B, B1 = 0,55, sin espera por aire, propiedad del freno de
   estación): comprobar que para a < 10 m del tablón (antes 45 y 63 m cortos), que no hay
   alternancias APPLY↔RELEASE y que no hay `air_fill` / `air_recharge`. Medir además B2 y B3
   (hoy sin datos) y revisar el perfil `…DMS_A_C.json` (B1 −0,38, n = 999). Hay ya un fixture y
   `parity_jsonl.py` sirve también para la 323 (`logs/v2/20261023T211407Z_…`).
3. **Un solo dueño por episodio de frenado** (continuación de §7.1 e) — *cambio de lógica, su propio
   commit y su propia validación; solo tras el punto 1.* El parpadeo del cartel está tapado con
   `_limit_plan_owns_brake`, pero siguen existiendo siete caminos de soltar independientes del
   plan. Siguiente paso: que soltar un freno comprometido sea una transición del plan (con
   histéresis explícita) y que los caminos de `decision_release` actúen solo sobre freno heredado.
4. **Sin juego, bajo riesgo** (se pueden hacer en cualquier momento):
   - ~~guardar el script de paridad~~ (hecho: `V2/scripts/parity_jsonl.py`);
   - ampliar `test_vehicle_contract.py` con parada en andén y soltar al salir (§5.10);
   - pruebas propias de `cli` y decidir si se conserva `diagnostic_mc_ipc` (§3.1);
   - partir `loop._step_core` (346 líneas) en pasos con nombre, con el mismo método de paridad.
5. **Con sesión o decisión de diseño:**
   - modelo de coast con pendiente (`station_coast_release_in_motion` asume 0,095 m/s² y en bajada
     del −1 % el tren aceleró; §7.4);
   - hueco del ACK ok (§4): marcar pendiente también con ACK ok; test del reenvío y validación
     (**medido en §7.3: 13 de 16 y 75 de 138 mandos repetidos a < 1 s**);
   - caducar una distancia de estación congelada con el tren en marcha (defensa en profundidad de
     §7.3), y averiguar por qué un poll llega como `track_only`;
   - defensa en profundidad (b) de §7: no emitir `P1-CRITICO-STATION` a alta velocidad si la
     distancia viene del ancla y acaba de saltar;
   - física real de la M3A (`physics` del JSON, hoy heredada de la 323): sesión de calibración de
     frenado;
   - ventana de aprendizaje de 2 s (§4): decisión de diseño pendiente;
   - distancia al tablón a lo largo de la vía (§7), tras validar con captura.
6. **Trenes nuevos** (cuando se hayan sondeado): según [TRENES_DLC.md](TRENES_DLC.md), un
   representante por familia (diésel de EE. UU. con dinámico, eléctrico alemán, metro o UK
   combinada) antes de decidir «archivo por tren». Criterio: operación nueva → adaptador nuevo;
   solo números nuevos → JSON. El paso 5 ya hecho es el que lo prepara. Antes, el modelo de palanca
   de §2.6 (decel objetivo → posición), que toca cartel, FSM de andén, `platform_bleed` y
   aprendizaje a la vez: solo con las sesiones de referencia 323 y M3A ya grabadas.
7. **Al final:** partir `session_report.py` (métricas / render HTML) y reorganizar carpetas
   (§2.4 paso 5).

Riesgos abiertos que conviene no olvidar: el feedback por muesca (`fb_escalated`) ya no cambia el
mando MC del cartel (el lazo se cierra al recalcular la decel necesaria cada tick; una curva muy
optimista tardaría varios ticks en corregirse); la envolvente monótona frena algo más fuerte que
antes también en andén (los tests siguen pasando, sin sesión que lo confirme); y el replay offline
es en lazo abierto: demuestra qué decide el código con esas entradas, no que el tren deje de
oscilar.
