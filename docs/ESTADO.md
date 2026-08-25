# Estado del proyecto — tablero visual

Vista tipo [FlowPlan](https://github.com/Bariskau/flowplan) **sin instalar nada**: solo markdown +
Mermaid.
Se abre en Cursor, GitHub o cualquier visor que renderice Mermaid.

**Detalle largo:** [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md) · **Runtime frenos:**
[FLUJO_FRENOS.md](FLUJO_FRENOS.md) · **Física / aprendizaje:**
[FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md) ·
**Paridad:** [DASTSC_PARITY.md](DASTSC_PARITY.md)

Última revisión: **2026-08-25** · **Estudio activo:** pasos **7–14** del
[árbol cronológico](assets/esqueleto_flujo_cronologico.svg) (numeración = círculos del SVG)

---

## Árbol cronológico — pasos 1, 2, 3 (LECTURA)

Imagen de referencia (abrir en el IDE o navegador — **las ramas están en el SVG**):

**[esqueleto_flujo_cronologico.svg](assets/esqueleto_flujo_cronologico.svg)** — pasos 1→14,
~20 Hz, arriba = primero. Ramas visibles: paso **1** (HUD + DriverAid → GetData), paso **3**
(probe + HTTP + HUD DB → `_telem`), paso **6** (FSM → P1 → HOLD), pasos **7–11**
(coordinator → 8 limit / 9 station / 10 planner → BrakeCommand).

Estos tres pasos son **solo lectura**: del juego (UE4SS/Lua) hasta el dict de telemetría que
consume el autopilot. **Aún no** hay decisión de freno ni escritura de mandos.

```mermaid
```

| Paso SVG | Archivo | Entrada | Salida |
| --- | --- | --- | --- |
| **1** | `mods/TelemetryProbeMod/Scripts/main.lua` | APIs UE (`HUD_Get*`, `GetDriverAidData`) | Una línea TSV en disco |
| **2** | `tsw6/telemetry/tsw_ue4ss_reader.py` | `GetData.txt` | `ProbeSnapshot` (dataclass) |
| **3** | `tsw6/telemetry/tsw_telemetry_source.py` | `ProbeSnapshot` + caché HTTP | `dict` en `_telem` (GUI/autopilot) |

**Ruta IPC (Windows):** `%TEMP%\TSW6Bridge\GetData.txt`
Ejemplo: `C:\Users\<usuario>\AppData\Local\Temp\TSW6Bridge\GetData.txt`

**Frecuencia:** Lua escribe cada **0,05 s** (~20 Hz) en `ReceiveTick`; Python lee el archivo en
cada `poll()` del autopilot (~20 Hz).

---

### Paso 1 — `main.lua` (UE4SS, dentro del juego)

**Qué hace:** en cada tick del jugador, lee la cabina y **sobrescribe** `GetData.txt` con una sola
línea `clave=valor` separada por espacios. En el mismo hook, si existe
`TSW6ApplyCommands.flag`, lee `SendCommand.txt` y aplica mandos (eso es el paso **14→1** del ciclo
siguiente; aquí solo importa la **escritura** de telemetría).

**Hook:** `TS2DefaultPlayerController_C:ReceiveTick` · **Teclas:** F7 on/off probe · F8 volcado
manual + dump DriverAid al log UE4SS.

#### APIs Lua que lee (origen en el motor)

| Dato en GetData | API Lua (actor / controller) | Uso en autopilot |
| --- | --- | --- |
| `speed_ms` | `drivableActor:HUD_GetSpeed` | Velocidad instantánea (**congelada** en Python: sin caché) |
| `power`, `power_neg` | `HUD_GetPowerHandle` | Tracción/freno combinado UK |
| `handle_notch` | derivado: `4 + round(power)` con signo | Muesca 0–8 mostrada en GUI |
| `train_brake`, `loco_brake`, `dyn_brake` | `HUD_GetTrainBrakeHandle`, `…Locomotive…`, `…Electric…` | Freight / diagnóstico |
| `accel_ms2` | `HUD_GetAcceleration` | Learner, física decider |
| `max_speed_ms` | `HUD_GetMaxPermittedSpeed` | Techo ATS |
| `speed_limit_ms` | `GetDriverAidData` → `SpeedLimit` | Cartel actual (mph→ms en parser) |
| `gradient_pct` | `GetDriverAidData` → `gradient` | Perfil freno / learner |
| `dist_limit_cm`, `next_limit_ms` | `distanceToNextSpeedLimit`, `nextSpeedLimit` | **P1** — 1.er cartel adelante |
| `dist_limit2_cm`, `next_limit2_ms` | cola `nextSpeedLimits[]` (2.º límite) | Cola planning probe |
| `odo_m` | `Simulation.Axle_1_1.TotalDistanceTravelled_M` | Detectar tren parado (hold distancias) |
| `vehicle` | `actor:GetClass():GetFName()` | Layout UK combined vs freight |
| `doors_open` / `doors_telem` | componentes `PassengerDoor_*` | FSM estación |
| `doors_dmi` | mensajes DMI en DriverAid | Informativo; FSM prioriza `doors_telem` |
| `seq` | contador Lua incremental | Saber si hay línea nueva (resync planning) |

**Lógica extra en Lua (importante para entender distancias):**

- Si el tren **no se mueve** (odómetro o posición actor), **mantiene** las distancias de límite

  anteriores (`hold_planning_if_stationary`) — evita que bajen al pausar con ESC.

- Si `dist_limit_cm ≤ 0` (ya en el cartel), **promueve** el siguiente límite de la cola.

#### Formato de línea (ejemplo real)

```text
```

Cada campo es opcional salvo que Lua lo tenga; `?` = desconocido (parser → `None`).

---

### Paso 2 — `tsw_ue4ss_reader.py` (parser puro)

**Qué hace:** lee **solo el archivo** — no HTTP, no autopilot. Convierte texto → tipos Python.

#### Flujo interno

```text
```

| Función | Rol |
| --- | --- |
| `default_getdata_path()` | `%TEMP%\TSW6Bridge\GetData.txt` |
| `parse_probe_line(line)` | Split por espacios, `key=value`; ints en `seq`/`handle_notch`; bools `0/1` |
| `read_probe_file(path)` | Devuelve `ProbeSnapshot` o `None` si no hay speed |
| `ProbeSnapshot.planning_dict()` | Reempaqueta límites al formato `driver_aid_parser` (cm→planning P1) |
| `ProbeSnapshot.to_telemetry_dict()` | Vista monitor (`probe_ue4ss.bat`, tests) |

#### Campos en `ProbeSnapshot` (lo que “sale” del paso 2)

| Campo | Tipo | Desde GetData |
| --- | --- | --- |
| `seq` | `int?` | `seq=` |
| `speed_ms` | `float?` | obligatorio para considerar muestra válida |
| `power`, `power_neg` | `float`, `bool` | mandos UK |
| `handle_notch` | `int?` | o calculado con `power_to_combined_notch()` |
| `train_brake`, `loco_brake`, `dyn_brake` | `float?` | |
| `accel_ms2`, `max_speed_ms`, `speed_limit_ms` | `float?` | |
| `gradient_pct` | `float?` | |
| `dist_limit_cm`, `next_limit_ms`, `dist_limit2_*` | `float?` | planning límites |
| `odo_m` | `float?` | |
| `doors_*` | `bool?` | |
| `vehicle` | `str` | clase UE del tren |

**Regla:** este módulo **no fusiona** estaciones HUD ni HTTP. Eso es paso 3.

**Herramientas CLI:** `python -m tsw6.telemetry.tsw_ue4ss_reader` · `--log` · `--benchmark 30`

---

### Paso 3 — `tsw_telemetry_source.py` (fusión y dict final)

**Qué hace:** capa que usa el autopilot (`TswTelemetrySource`). Con modo `ue4ss`:

1. Lee `ProbeSnapshot` (paso 2).
2. Construye telemetría **base** con `_telem_from_probe()` — velocidad directa, sin tocar planning.
3. **Mezcla** planning lento por HTTP (estaciones, TrackData, horario HUD).
4. Aplica distancias de límites con `_apply_probe_planning()` cuando el probe trae `dist_limit_cm`.
5. Guarda el resultado en `self._telem` (hilo seguro con lock).

#### Prioridad de fuentes (doc del módulo)

| Dato | Fuente primaria | Fallback HTTP (`-HTTPAPI`) |
| --- | --- | --- |
| Velocidad, mandos, acel | Probe ~20 Hz | `FastControlReader` |
| Gradiente | Probe `gradient_pct` | `DriverAid.Data` en `_poll_slow` |
| Distancia 1.º/2.º límite | Probe (`planning_dict`) | Odometría Python entre polls HTTP |
| Estaciones comerciales | — | `DriverAid.TrackData` + `hud_timetable.py` / `tsw_hud.db` |
| Puertas (FSM) | Probe `doors_telem` | `PassengerDoor_*` vía API |
| `next_stop`, `arr`/`dep` | — | HUD DB + filtro horario |

#### `_telem_from_probe()` — campos que salen del probe (no negociables)

| Clave en `dict` | Origen | Nota |
| --- | --- | --- |
| `speed_mph` | `speed_ms × 2.236936` | **Congelado 2026-08-22** — tests `test_speed_*` |
| `handle_notch` | `snap.combined_handle_notch()` o 4 | |
| `accel_mps2` | probe | |
| `gradient_pct` | probe; si falta, HTTP cache o `0.0` | |
| `limit_mph` | `speed_limit_ms` | cartel actual |
| `train_brake_value`, `ind_brake_value`, `dyn_brake_value` | probe | |
| `doors_telem`, `doors_dmi` | probe | `_apply_door_state` latchea |
| `telemetry_source` | `"ue4ss"` | |
| `telemetry_age_ms` | mtime `GetData.txt` | frescura |
| `probe_seq` | `snap.seq` | |

#### `_merge_planning()` — lo que añade HTTP (no está en GetData)

| Clave típica | Para qué |
| --- | --- |
| `stations[]` | Lista paradas con distancia en vía |
| `next_stop`, `next_stop_name` | Próxima parada comercial |
| `next_stop_arrival`, `next_stop_departure` | `station_eta` → P1 planner |
| `schedule_source` | `hud_db` / `timetable_json` / `trackdata` |
| `hud_timetable_id`, `hud_route_name` | GUI horario |
| `service_name` | Filtro paradas por servicio |
| `speed_limits_ahead[]` | Cola normalizada (parser) |
| `distance_next_m`, `next_limit_mph` | Probe **sobrescribe** si hay `dist_limit_cm` |

#### `_apply_probe_planning()` — reglas de distancia (límites)

- Resync cuando cambia `probe_seq` (línea nueva de Lua).
- Si el tren **congelado** (`probe_motion_frozen`) o velocidad &lt; 0,5 mph: **no acepta** que

  baje `distance_next_m` (misma idea que hold en Lua).

- `planning_hold=True` (autopilot pausado): congela distancias overlay.
- **No usa odometría Python** para límites si vienen del probe — solo cm del DriverAid.

#### Cómo lo consume el autopilot

```text
```

#### Conexión y fallos

| Método | Cuándo |
| --- | --- |
| `try_connect_ue4ss()` | Existe `GetData.txt` + `speed_ms` válido |
| `connect_fast()` | GUI arranque sin esperar HTTP |
| `probe()` | UE4SS o fallback `tsw_api` |
| Stale | Si mtime &gt; **0,75 s** y aún no conectado → “F7 en cabina” |

**Pendiente en esta capa (tarjetas C1–C2):** `distanceToSignal` / aspecto DANGER **no** están en
GetData ni en `_telem` hoy → `signal_brake` sigue stub.

---

### Checklist estudio pasos 1–3

| # | Pregunta | Dónde mirar |
| --- | --- | --- |
| 1 | ¿Lua escribe ~20 Hz? | UE4SS.log `[TelemetryProbe]` o F8 |
| 2 | ¿`seq` sube cada tick? | GUI `probe seq=…` o `probe_ue4ss.bat` |
| 3 | ¿Parser coincide con línea cruda? | `read_probe_file` / tests `test_tsw_ue4ss_reader` |
| 4 | ¿`speed_mph` = probe directo? | tests `test_speed_*` en `test_telemetry_source` |
| 5 | ¿Estaciones vienen de HTTP aunque haya probe? | log `schedule_source=hud_db`, GUI horario |
| 6 | ¿Distancias límite bajan al avanzar? | log `probe_dist=`, `Δprobe=` cada ~3 s |

**Siguiente bloque del SVG:** **CICLO + DECISIÓN** pasos **4–6** (abajo). Pasos **7–14** en
[FLUJO_FRENOS.md](FLUJO_FRENOS.md).

---

## Árbol cronológico — pasos 4, 5, 6 (CICLO + DECISIÓN)

```mermaid
```

| Paso SVG | Archivo | Entrada | Salida |
| --- | --- | --- | --- |
| **4** | `tsw6/autopilot/autopilot_core.py` | `dict` `_telem` | Ciclo completo (~20 Hz) |
| **5** | `tsw6/autopilot/train_state.py` | `_telem` + estado FSM/decider | `TrainState` |
| **6** | `tsw6/autopilot/speed_decider.py` | `TrainState` | `action` + `brake_command` (solo P1) |

### Paso 4 — `autopilot_core.tick()`

| Fase | Qué hace |
| --- | --- |
| Telemetría | `connection.get_telemetry()` → paso 3 |
| Física | `decider.update_physics()`, `feed_learner()` |
| Decisión | `build_train_state()` → `decider.decide()` |
| Watchdog | `SafetyWatchdog.check()` — override `BRAKE_FAST` si +5 mph ≥3 s |
| Ejecución | `brake_command_for()` → `handle_controller.execute()` → IPC |
| Sin P2 | Eliminado `_decide_p2()` y `p2_overspeed_brake_command()` (2026-08-25) |

### Paso 5 — `build_train_state()`

Campos clave para P1:

| Campo `TrainState` | Origen `_telem` | Uso P1 |
| --- | --- | --- |
| `speed_mph`, `limit_mph` | probe | Cinemática |
| `next_limit_mph`, `distance_next_m` | probe + planning | `limit_brake` |
| `speed_limits_ahead[]` | HTTP + probe | Cola carteles |
| `next_stop_distance_m`, `next_stop_arrival` | HUD / TrackData | `station_brake` |
| `station_state` | FSM interna | Prioridad / reset P1 |
| `handle_notch`, `throttle_notch` | probe | `COAST_THROTTLE` antes de APPLY |

### Paso 6 — `speed_decider.decide()` (orden estricto)

| # | Capa | Condición | Acción típica |
| --- | --- | --- | --- |
| 1 | Pausa | `state.paused` | `PAUSED` |
| 2 | **FSM** | APPROACHING / STOPPED / DEPARTING | `HOLD`, `COAST`, perfil `effective_limit` |
| 3 | Salida andén | DEPARTING + freno residual | `COAST` |
| 4 | **Marcador DMI** | `brake_marker_m` cerca | `BRAKE` / `BRAKE_FAST` |
| 5 | **P1** | `_p1_should_run()` | `BrakeCoordinatorV2.evaluate()` → `HOLD`/`COAST`/`RELEASE` + IPC |
| 6 | Sin plan | P1 devuelve `None` | **`HOLD`** (conductor o watchdog) |

**Código eliminado (auditoría 2026-08-25):** no queda `_decide_p2`, `p2_overspeed_brake_command`,
`P2_LIMIT_BRAKE_THRESHOLD` ni tests P2. Comentarios en `governor_constants` actualizados.

---

## Árbol cronológico — pasos 7→14 (P1 FRENO + EJECUCIÓN + JUEGO)

**Regla de numeración:** los círculos del
[SVG](assets/esqueleto_flujo_cronologico.svg) son la fuente de verdad. Las cajas **sin círculo**
(`priority + cluster`, `signal_brake` punteado) son sub-fases **dentro del paso 7**, no pasos nuevos.

El paso **7** es `BrakeCoordinatorV2.evaluate()` (`coordinator.py`), invocado desde el paso 6
cuando `_p1_should_run()` es verdadero. Los pasos **8–10** son ramas en paralelo que el coordinator
consulta; **11** es el `BrakeCommand` resultante.

```mermaid
flowchart TB
  IN["7 BrakeCoordinatorV2.evaluate()"]
  R["RELEASE / emergencia / sin objetivo"]
  PAR["ramas en paralelo"]
  LIM["8 limit_brake"]
  STN["9 station_brake"]
  PLN["10 planner"]
  SIG["signal_brake stub sin nº"]
  PRI["priority + cluster sin nº"]
  BC["11 BrakeCommand"]
  HC["12 handle_controller.execute()"]
  IPC["13 tsw_ipc_bus"]
  LUA["14 main.lua aplica"]

  IN --> R
  R --> PAR
  PAR --> LIM
  PAR --> STN
  PAR --> PLN
  PAR -.-> SIG
  LIM --> PRI
  STN --> PRI
  PLN --> PRI
  SIG -.-> PRI
  PRI --> BC --> HC --> IPC --> LUA
```

| Paso SVG | Módulo | Notas |
| --- | --- | --- |
| **7** | `coordinator.evaluate()` | Orquesta RELEASE, emergencia, parada unificada, prioridad |
| **8** | `limit_brake.py` | Cartel → perfil B1–B3, `dist_start` |
| **9** | `station_brake.py` | Entrada andén HUD / parada comercial |
| **10** | `planner.py` | Perfil físico, ETA, cluster 350 m (llamado desde **9**) |
| *(sin nº)* | `priority.py` + `cluster.py` | Caja fusión SVG: elige 1 plan; `uni=Y` |
| *(sin nº)* | `signal_brake.py` | Caja punteada SVG: stub DANGER (tarjeta C1) |
| **11** | `BrakeCommand` | `to_brake_command()` → APPLY / RELEASE → `decider.brake_command` |
| **12** | `handle_controller.execute()` | Prioridad comando IPC P1 |
| **13** | `tsw_ipc_bus` | `SendCommand.txt` + flag |
| **14** | `main.lua` | `PowerBrakeHandle` en juego → vuelta al paso **1** |

### Paso 7 — `evaluate()` (orden interno del coordinator)

| Fase | Qué hace | Si no aplica |
| --- | --- | --- |
| **A. Entrada** | Cola `speed_limits_ahead[0]` → `_nl`, `_dn`; log `gap`, `p1eta` | — |
| **B. RELEASE** | Si hay freno y ya vas al objetivo → `RELEASE` neutro | `release_blocked:unified_stop` |
| **C. Sin objetivo** | Sin estación y sin cartel útil | `sin_objetivo_v2` → `None` |
| **D. Parada unificada** | Cartel+andén ≤350 m y no caben dos frenadas → `uni=Y` | — |
| **E. Emergencia** | Andén/señal muy cerca + mucha velocidad | B3 o muesca 0 |
| **F. Candidatos** | Pasos **8–10** (+ `signal` stub) en paralelo | `sin_plan_activo` |
| **G. Prioridad** | `select_urgent_target()` (caja SVG sin nº) | — |
| **H. Coast latch** | Tras RELEASE en cartel: no re-frenar de golpe | `COAST LATCH` → `HOLD` |
| **I. Comando** | Paso **11**: `to_brake_command()` → APPLY / RELEASE | `perfil activo` → `HOLD` |

**Retorno:** `(action, effective_limit)` + estado público `last_brake_command`, `last_target`,
`last_debug` (GUI y línea de ciclo `p1tgt=… p1cmd=…`).

### Ejemplos (E1 Cross-City)

| Escenario | Qué hace el coordinator |
| --- | --- |
| 60 mph, cartel 55 @ 800 m | `sin_plan_activo` hasta `dist_start` &lt; zona; luego `v2 SPEED_LIMIT B1` |
| 60 mph, cartel 55 + andén @ 350 m (`gap≈0`) | `uni=Y`; gana **estación**; RELEASE @ ~55; coast al andén |
| Tracción en notch 6, plan B2 activo | `COAST_THROTTLE` un tick, luego `APPLY` B2 |
| Casi parado en andén con freno | `RELEASE` vía `to_brake_command` (parada) |
| Andén a 30 m, 45 mph | `P1-EMERGENCIA-STATION` → B3 |

**Siguiente bloque SVG:** pasos **12–14** (ejecución IPC y vuelta al juego). Ver
[FLUJO_FRENOS.md](FLUJO_FRENOS.md).

### Pasos 12–14 — ejecución

| Paso | Qué hace |
| --- | --- |
| **12** | `handle_controller.execute(action, brake_command)` — si hay `BrakeCommand` P1, manda notch absoluto |
| **13** | `tsw_ipc_bus` escribe `SendCommand.txt` y activa flag |
| **14** | `main.lua` aplica `PowerBrakeHandle`; siguiente tick vuelve al paso **1** |

---

Leyenda de tipos (como FlowPlan):

| Tipo | Color en diagrama | Significado |
| --- | --- | --- |
| **Test** | verde | Validado / cerrado |
| **Edit** | azul | Código integrado, falta validar in-game |
| **Create** | naranja | Implementar o cablear |
| **Research** | gris | Investigar / sesión en juego |
| **Planning** | morado | Diseño / doc / arquitectura |

```mermaid
```

**Regla:** no abrir trabajo en «Después» hasta cerrar la cadena `E1 → C1 → C2`.

---

## Tarjetas (detalle)

### ✅ Cerrado — no reabrir salvo regresión

| ID | Tarjeta | Archivos | Doc |
| --- | --- | --- | --- |
| T1 | Velocidad probe fluida ~20 Hz | `tsw_telemetry_source.py` | [PENDIENTE § Velocidad](PENDIENTE_DYNAMICHUD.md#velocidad-actual--congelado--2026-08-22) |
| T2 | Mandos IPC notch absoluto | `tsw_ipc_bus.py`, probe Lua | [DASTSC_PARITY](DASTSC_PARITY.md) |
| T3 | P1 v2 consolidado | `tsw6/braking/v2/*` | [BRAKE_V2](BRAKE_V2.md) |
| T4 | Horario estaciones arr/dep GUI | `hud_timetable.py` | [HUD_TIMETABLE](HUD_TIMETABLE.md) |
| T5 | Parada unificada cartel+andén | `coordinator.py`, `cluster.py` | [FLUJO_FRENOS](FLUJO_FRENOS.md) |
| T6 | `station_eta` al planner | `train_state` → `planner.py` | [BRAKE_V2 § Pendiente](BRAKE_V2.md#pendiente) |
| T7 | Eliminar capa P2 reactiva | `speed_decider.py`, `command.py` | § Sin P2 abajo |

### 🎯 Hacer ahora

| ID | Tarjeta | Qué comprobar | Log / señal |
| --- | --- | --- | --- |
| **E1** | Validar in-game frenado v2 | 2R17 Cross-City, cartel 60 + andén | `uni=Y`, `gap=`, `p1eta=`, RELEASE @55 |
| **C1** | Telemetría señal → P1 | `signal_brake.py` hoy stub | `distanceToSignal`, aspecto DANGER en `TrainState` |
| **C2** | Distancia tablón fina | OCR/GPS cada tick | `station_brake` / coordinador |

### ⏸️ Después

| ID | Tarjeta | Notas |
| --- | --- | --- |
| R1 | Estabilidad probe 10+ min | Sesión A4 |
| C3 | Anti-fantasma turnaround | `station_traveled_m`, `station_anchor_m` |
| C4 | 2º límite en log ciclo | `speed_limits_ahead[1]` |
| R2 | SD40-2 freight | [FREIGHT_NA](FREIGHT_NA.md) |
| P1 | Cosmética mod / flag armed | Baja prioridad |

---

## Flujo runtime completo (14 pasos — resumen)

Ver estudio detallado **pasos 1–3** arriba. Resto: [FLUJO_FRENOS.md](FLUJO_FRENOS.md) ·
[esqueleto_flujo_cronologico.svg](assets/esqueleto_flujo_cronologico.svg).

| Sección SVG | Pasos | Qué pasa |
| --- | --- | --- |
| **LECTURA** | 1–3 | Juego → GetData → Python telemetría |
| **CICLO** | 4–5 | `tick()` + `TrainState` |
| **DECISIÓN** | 6 | `speed_decider`: FSM → DMI → P1 → `HOLD` |
| **P1 FRENO** | 7–11 | **7** coordinator → **8–10** ramas → priority/cluster → **11** `BrakeCommand` |
| **EJECUCIÓN** | 12–13 | `handle_controller` → IPC (watchdog teclado si sin plan) |
| **JUEGO** | 14 | Lua aplica mando → vuelta al **1** |

```mermaid
```

Imágenes: [esqueleto_arquitectura.svg](assets/esqueleto_arquitectura.svg) ·
[esqueleto_flujo_capas.svg](assets/esqueleto_flujo_capas.svg)

---

## Criterios MVP (resumen)

| # | Criterio | Estado |
| --- | --- | --- |
| 1 | ≥15 Hz velocidad + mando en Python | ✅ |
| 2 | Lua ≈ HTTPAPI (323) | ✅ |
| 3 | `aprender.bat` sin RailBridge | ✅ |
| 3b | P1 v2 límite + estación + prioridad | ✅ código · 🔄 validar E1 |
| 4 | Sin mandos colgados al cerrar | ✅ |
| 5 | Autopiloto sin `-HTTPAPI` (mandos) | ✅ |

---

## Sin P2 (2026-08-25) — cerrado

**Problema:** la capa P2 reactiva (`speed` vs `limit`) chocaba con P1 cuando cartel y estación
estaban agrupados (~350 m): frenaba al 55 mph con la estación aún lejos.

**Solución:** eliminado del código. Si P1 no tiene plan → `HOLD`. Red de seguridad: **watchdog**

(+5 mph durante ≥3 s → `BRAKE_FAST` por teclado).

| Responsable | Qué |
| --- | --- |
| **P1** | Plan por distancia (cartel, andén, señal) + `COAST_THROTTLE` / `BrakeCommand` IPC |
| **FSM** | Estados APPROACHING/STOPPED/DEPARTING + perfil `effective_limit = k√dist` |
| **Marcador DMI** | Advisory brake marker en vía |
| **Watchdog** | +5 mph durante ≥3 s → override `BRAKE_FAST` |

Capa ATP/ACK eliminada del decider (telemetría `ack_required` sigue en probe por compatibilidad).

**Archivos tocados:** `speed_decider.py`, `command.py`, `governor_constants.py`, `v2/physics.py`,
tests,
`FLUJO_FRENOS.md`, SVGs `esqueleto_flujo_*.svg`.

---

## Física y aprendizaje online

Documento dedicado: **[FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md)**

| Pregunta | Respuesta corta |
| --- | --- |
| ¿El autopilot ya aprende? | **Sí** — **0–8 por defecto**; desmarcar Auto-aprender → solo 0–3 al frenar |
| ¿Para qué `aprender.bat`? | Mismo `OnlineLearner`, pero **guiado** (matriz, conducción manual sistemática) |
| ¿Perfil genérico? | Hoy: constantes 323 + fracciones B1–B3; **pendiente:** semillas `data/profiles/seed/` |
| ¿`0.80` vs `1.071`? | **Unificado** → una sola `MAX_DECEL_MS2` (1.071 m/s²) para P1 y fallbacks v2 |

---

## Cómo mantener este tablero

1. **Cambiar estado:** editar el bloque Mermaid o la tabla (commit en git).
2. **No duplicar:** el detalle técnico sigue en `PENDIENTE_DYNAMICHUD.md`; aquí solo el mapa.
3. **Ver el diagrama:** preview markdown en Cursor (`Ctrl+Shift+V`) o en GitHub al pushear.

No hace falta FlowPlan, Obsidian ni Node — esto es la versión mínima del mismo concepto.
