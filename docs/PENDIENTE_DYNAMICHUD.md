# Pendiente — DynamicHUD v1.0.0 → TelemetryBridge

**Objetivo:** telemetría **in-process** (~17–20 Hz) vía UE4SS y puente a Python (`GetData.txt`).

**Estado:** ✅ MVP Class 323 (2026-08-24) — velocidad congelada · mandos IPC · planning límites probe
· **horario HUD estaciones + arr/dep en GUI (validado in-game)** · **P1 frenado v2 consolidado en
`braking/v2/`** · `station_eta` cableado al planner · log ciclo ampliado para depuración v2
· SD40-2 pendiente

**Relacionado:** [ARQUITECTURA.md](ARQUITECTURA.md) · [BRAKE_V2.md](BRAKE_V2.md) ·
[DASTSC_PARITY.md](DASTSC_PARITY.md) ·
[FREIGHT_NA.md](FREIGHT_NA.md) · [GUIA.md](GUIA.md)

---

## Foco actual — no distraerse

### ✅ Cerrado (no reabrir salvo regresión)

| Tema | Dónde | Nota |
| --- | --- | --- |
| Velocidad probe ~20 Hz | `tsw_telemetry_source` | Tests `test_speed_*` obligatorios |
| Mandos IPC B4 | `tsw_ipc_bus` + probe Lua | Sin `-HTTPAPI` para escribir; **preferido** frente a teclado (notch absoluto) |
| P1 frenado Dastsc | `braking/v2/` → `SpeedDecider` | Todo en v2; eliminado `archive/braking_v1/` |
| RELEASE cartel+andén unificado | `v2/coordinator.py` + `v2/cluster.py` | Soltar al cartel y coast; `should_delay_unified_station_plan` |
| `station_eta` → planner | `TrainState.next_stop_arrival` → `SpeedDecider` | HUD `HH:MM:SS` normalizado a `HH:MM` |
| Log ciclo v2 | `autopilot_core._log_cycle` + `investigate_suffix` | `thr`, `gap`, `wd`, `p1eta`, `uni`, `p1tgt/p1ds` |
| Horario HUD paradas | `hud_timetable.py` + BD release | Paradas, distancias, **arr/dep en GUI** (validado) |
| Gradiente en probe | `gradient_pct` en GetData.txt | Class 323 validado |
| **Ventana APPLY física** | `v2/physics.py` | Sustituye 60/80/30/150 m fijos; ver [BRAKE_V2.md](BRAKE_V2.md) |

### 🎯 Hacer ahora (impacto paridad Dastsc)

| # | Tarea | Por qué |
| --- | --- | --- |
| 1 | **Validar in-game** frenado v2 (2R17 Cross-City) cartel+andén + RELEASE @55 | Confirmar fix unified; log `gap=`, `uni=Y`, `p1eta=` |
| 2 | **Telemetría señal** (`distanceToSignal`, aspecto DANGER) → `TrainState` + P1 | `signal_brake.py` es stub |
| 3 | **Distancia tablón** OCR/GPS cada tick → `station_brake` / coordinador | Parada andén menos precisa que Dastsc |
| 4 | **Contención cartel en bajada** (`limit_brake` + `uni=Y`) | Mantener plan P1 cerca del límite con `gradient_pct < -0.3‰`; retirado 2026-08-26 |

### ⏸️ Después (no bloquean MVP UK)

- `station_traveled_m` / `station_anchor_m` → planner (anti-fantasma turnaround)
- 2.º límite en cola visible en log ciclo (`speed_limits_ahead[1]`)
- SD40-2 probe (A3 freight) + [FREIGHT_NA.md](FREIGHT_NA.md)
- Campos probe extra (patinaje, manómetros, `IS_GetBrakeState`)
- Renombrar mod a `TelemetryBridgeMod`, flag “autopilot armed”
- Estabilidad 10+ min (A4), benchmark formal vs HTTP

**Regla:** si no está en «Hacer ahora», no abrir PR ni refactor hasta cerrar 1–3.

### Parada servida por puertas (2026-08-26)

Si el tren queda en `APPROACHING` pero la distancia al tablón salta (parada aceptable a mitad de
andén),
la FSM **no** pasaba a `STOPPED` (`stop_dist_m` > ventana andén). La GUI seguía mostrando la misma
parada.

**Fix:** `_handle_door_service_at_stop` en `governor_station.py` — ciclo puertas **sin** umbral de
distancia:

1. Parado (`spd ≤ STATION_STOPPED_MPH`) + puertas abiertas → `STOPPED` (si venía de `APPROACHING`)
2. Puertas cerradas tras haber abierto → `DEPARTING` + `served_bases` (siguiente parada en GUI)

Log esperado: `FSM: puertas abiertas`, `FSM: … → DEPARTING (puertas cerradas, servida)`.

---

## P1 v2 — estado y log de depuración (2026-08-24)

Arquitectura: [BRAKE_V2.md](BRAKE_V2.md). Todo el frenado vive en `tsw6/braking/v2/`.

### Integración autopilot — ✅

| Pieza | Ruta |
| --- | --- |
| Decisión | `speed_decider.py` → `BrakeCoordinatorV2.evaluate()` |
| Mandos | `handle_controller.py` ← `BrakeCommand` (notch IPC absoluto) |
| Física distancias | `governor_physics.py` → `v2/physics.py` |
| Horario parada | `telem.next_stop_arrival` → `TrainState` → `station_eta` → `v2/planner.py` |

### Log ciclo (`autopilot_*.log`) — campos v2

Línea de ciclo (cada ~2 s en DEBUG tras los 5 primeros INFO):

| Campo | Significado |
| --- | --- |
| `p1dbg` | Estado interno P1: `v2 SPEED_LIMIT B1`, `RELEASE→NEU`, `sin_plan_activo`, `release_blocked:…`, `perfil activo` |
| `p1tgt` / `p1d` / `p1ds` | Objetivo activo, distancia en vía, **distStart** (m hasta inicio de frenada; APPLY en ±zona física) |
| `p1apply` | `Y` = APPLY este ciclo |
| `p1cmd` / `p1r` | APPLY / RELEASE + razón |
| `uni=Y` | Parada unificada cartel+andén latched |
| `gap=` | Andén − cartel (m); cluster si &lt; 350 m |
| `p1eta=` | ETA pasada al planner (`HH:MM`, desde HUD `arr`) |
| `p1=B1→N3` | Comando P1 del ciclo |
| `thr=` | Muesca tracción (0 si sin tracción) |
| `wd=` | Watchdog override (p. ej. `BRAKE_FAST`) si distinto de `action` |
| `arr` / `dep` / `sched` | Horario HUD próxima parada |

Logger detallado: `[tsw.governor.v2] P1v2 …` en cada APPLY (cada ~100 ms).

### Qué mirar in-game

| Situación | Campos clave |
| --- | --- |
| Frenada al cartel | `p1apply=Y`, `P1v2 SPEED_LIMIT`, `p1ds` → 0 en ventana (~67 m @ 60 mph, no 60 fijo) |
| RELEASE bloqueado | `p1dbg=release_blocked:station` — estación en ventana APPLY |
| 60→55 + andén cercano | `uni=Y`, `gap=<350m`, RELEASE al llegar a ~55 (`p1dbg=RELEASE→NEU`) |
| Coast con horario | `p1eta=8:18`, B2 más tarde si vas adelantado al `arr` |
| Freno atascado | `notch=3` + `p1dbg=sin_plan_activo` sin `RELEASE→NEU` → bug |

### Pendiente P1 v2 (código)

- [ ] `signal_distance_m` / `signal_aspect` en `TrainState` y `SpeedDecider.evaluate()`
- [ ] `station_traveled_m` / `station_anchor_m` (supresión turnaround en `v2/planner.py`)
- [ ] OCR distancia tablón → `station_brake` / coordinador
- [ ] **Contención en bajada** — plan de cartel activo a velocidad del límite si `gradient_pct <

  -0.3‰` (evitar `sin_plan_activo` por gravedad); retirado a petición 2026-08-26, reimplementar con
  validación in-game

- [ ] 2.º límite en cola en log ciclo
- [ ] Validar in-game post-fix RELEASE unified (sesión 2R17)

---

## Lectura vs escritura (importante)

| Capa | Fuente actual | ¿Requiere `-HTTPAPI`? |
| --- | --- | --- |
| **Lectura** (velocidad, mandos, acel) | `TelemetryProbeMod` → `GetData.txt` | **No** |
| **Escritura** (autopiloto mueve mandos) | `SendCommand.txt` (probe Lua) o HTTP PATCH fallback | **No** (IPC) / opcional HTTP |
| **Calibración** (`aprender.bat`) | Solo lectura | **No** (con probe activo) |
| **Autopiloto** (`iniciar_autopilot.bat`) | Lectura UE4SS + mandos IPC; planning HTTP + HUD DB | **No** (mandos); **sí** (paradas HUD) |
| **Planning distancias** | Probe 2 límites ~20 Hz + odometría HTTP | No (límites); sí (estaciones HUD) |

**Conclusión:** patrón Dastsc completo para mandos (`GetData.txt` + `SendCommand.txt`).
`-HTTPAPI` queda **opcional** (planning anticipatorio con 2 límites; gradiente ya en probe).

```text
```

---

## Qué es DynamicHUD (y qué NO hace)

| --- | --- |
| --- | --- |
| **Sí** | Paquete UE4SS + mod que oculta/muestra HUD según velocidad/objetivo |
| **Sí** | Plantilla Lua: `HUD_GetSpeed`, `GetDriverAidData`, `ReceiveTick` |
| **No** | No exporta telemetría ni escribe mandos por sí solo |
| **No** | No usar en producción: `enabled.txt` anula `mods.txt : 0` |

**TelemetryProbeMod** es el fork de solo lectura (sin `SetHudType`). DynamicHUD debe quedar
**desactivado** para el HUD normal del juego.

### Trampa `enabled.txt` (UE4SS)

Aunque `mods.txt` tenga `DynamicHUDMod : 0`, UE4SS carga el mod si existe:

`Mods\DynamicHUDMod\enabled.txt`

En log: `Mod 'DynamicHUDMod' disabled in mods.txt` → `has enabled.txt, starting mod`.
**Solución:** borrar ese archivo (no recrearlo). Reiniciar TSW6.

---

## Fase A — Investigar (en juego)

### A1. Instalar UE4SS — ✅

- Steam: merge `WindowsNoEditor\` → `...\Train Sim World 6\WindowsNoEditor\`
- Log: `UE4SS v3.0.1`, sin crash

### A2. DynamicHUDMod — ✅ (solo pruebas; dejar off en uso normal)

- `DynamicHUDMod : 0` en `mods.txt`
- Sin `DynamicHUDMod\enabled.txt`
- `TelemetryProbeMod : 1` en `mods.txt`

### A3. Validar APIs Lua vs HTTPAPI — ✅ Class 323

**Instalar:** `install_ue4ss_probe.bat`
**Monitor:** `probe_ue4ss.bat` · `probe_ue4ss_log.bat`
**Teclas cabina:** F7 on/off · F8 volcar

| Campo | Lua (probe) | HTTPAPI | 323 observado |
| --- | --- | --- | --- |
| `speed_ms` | `HUD_GetSpeed` | `HUD_GetSpeed` | ✅ |
| `power` / `handle_notch` | `HUD_GetPowerHandle` | `HUD_GetPowerHandle` | -4…+4 → 0–8 ✅ |
| `train_brake` | `HUD_GetTrainBrakeHandle` | idem | ✅ |
| `loco_brake` | `HUD_GetLocomotiveBrakeHandle` | idem | ✅ |
| `dyn_brake` | `HUD_GetElectricBrakeHandle` | idem | ✅ |
| `accel_ms2` | `HUD_GetAcceleration` | idem | ✅ |
| `speed_limit` | `GetDriverAidData.SpeedLimit` | parcial HUD | ✅ |
| `vehicle` | `GetClass():GetFName()` | `ObjectClass` | ✅ |
| `gradient_pct` | `GetDriverAidData` → `gradient` | `DriverAid.Data.gradient` | ✅ 323 (+ subida confirmado) |
| planning (estaciones, next limit) | `GetDriverAidData` dist/límites | limitado HTTP | ✅ 2 límites @ ~20 Hz |

Sesión ref.: `logs/ue4ss_probe_20260818_022527.txt` — **~17 Hz** medio.

- [x] Class 323 (`combined`)
- [ ] BNSF SD40-2 (`freight_na`) — en espera
- [x] Hz efectivo ~17–19

### A4. Riesgos — pendiente sesión larga

- [ ] Estabilidad 10+ min con hook `ReceiveTick`
- [ ] Compatibilidad tras update TSW
- [x] DynamicHUD + probe: no interferencia si DynamicHUD está off
- [ ] Solo escenarios offline propios

### A5. Formato IPC — ✅ decidido

- [x] **Opción A:** TSV una línea (estilo Dastsc) en `%TEMP%\TSW6Bridge\GetData.txt`
- [ ] JSONL / UDP — descartado por ahora

---

## Velocidad actual — congelado ✅ (2026-08-22)

**Validado in-game:** fluida en GUI autopilot (~20 Hz). **No tocar** salvo regresión en tests.

### Pipeline (único camino)

```text
```

| Regla | Detalle |
| --- | --- |
| Sin caché | Cada tick lee `GetData.txt`; `speed_mph` no pasa por `_planning_dist` |
| Sin odometría | La velocidad no se interpola ni estima en Python |
| Planning aparte | `_apply_probe_planning` solo toca distancias/límites, no `speed_mph` |
| Conversión | `speed_mph = speed_ms × 2.236936` (`MS_TO_MPH` en `governor_constants`) |

### Comprobar

```bat
```

`speed` debe subir/bajar al instante con el tren. En GUI: barra inferior `probe seq=…` avanza.

### Tests de regresión (obligatorio pasar antes de tocar)

- `test_speed_direct_from_probe_no_planning_touch`
- `test_speed_updates_each_probe_read`
- `test_tsw_ue4ss_reader.py` (parser `speed_ms`)

### Fuera de alcance (no mezclar con velocidad)

- Distancias a límites / planning — ver sección Planning abajo
- Mandos IPC — B4
- Aceleración suavizada en `SpeedDecider` — física del decider, no telemetría probe

---

### Gradiente — ✅ resuelto (Class 323, 2026-08-18)

**Fuente principal:** UE4SS probe (~18 Hz), **sin** `-HTTPAPI`.

| Capa | Ruta / campo |
| --- | --- |
| Lua | `controller:GetDriverAidData(driverAid)` → `driverAid.gradient` (número plano) |
| IPC | `gradient_pct=` en `GetData.txt` |
| Python | `tsw_telemetry_source` / `train_state.gradient_pct` (+ subida, − bajada) |

```lua
```

Validado in-game: HUD 0.4–1.0 % ↔ probe `grad: +1.000 %`. F8 vuelca `DriverAid dump` al log UE4SS.

**Fallback HTTP** (solo si el probe no trae `gradient_pct` o para comparar con `probe_ue4ss.bat
--api`):

```http
```

Campo: `"gradient": -0.62` (número en %, minúsculas). Poll lento en
`tsw_telemetry_source._poll_slow`
(~0,5–1 s), no en el bucle de 17 Hz.

Alternativa por eje (simulación): `Simulation/Axle_*_*.TrackGradient_DEG` vía HTTP explore.

### Planning (estaciones, next limit)

##### Límites de velocidad — ✅

- Probe: `dist_limit_cm`, `next_limit_ms`, `dist_limit2_*` en `GetData.txt` (~20 Hz)
- HTTP fallback + odometría entre polls
- **P1 activo:** `braking/v2/limit_brake.py` + `v2/command.py` (B1–B3 Dastsc)

##### Estaciones comerciales — ✅ planning / 🔄 frenado fino

- `hud_timetable.py` + `tsw_hud.db` (extractor TSW HUD)
- `DriverAid.PlayerInfo`: `currentServiceName` + `geoLocation`
- `DriverAid.TrackData.markers` filtrados por horario STOP
- Distancia tablón: `car_stop_signs` cuando TrackData no coincide (`hud_geo`)
- GUI: `schedule_source`, `[horario HUD #ID]`, próxima parada
- **Frenado andén:** `v2/station_brake.py` → `v2/planner.py`

Detalle setup: [HUD_TIMETABLE.md](HUD_TIMETABLE.md). Frenado: [BRAKE_V2.md](BRAKE_V2.md).

**Pendiente estaciones (solo foco 2–3 arriba):**

- [x] `planBrakeForStation` — vía `station_brake` + `v2/planner` (funcional)
- [x] `station_eta` — `next_stop_arrival` HUD → `SpeedDecider` → planner (reaction scale / coast)
- [ ] Pasar `signal_distance_m` / aspecto desde probe o HTTP → `signal_brake`
- [ ] Recalcular distancia tablón OCR/GPS cada tick (no solo odometría HTTP)
- [ ] `station_traveled_m` / `station_anchor_m` en telemetría (anti-fantasma turnaround)
- [ ] Estaciones en probe Lua (baja prioridad)

---

## Catálogo de datos (Lua / HUD) — qué existe y qué nos interesa

Fuente: dumps `tsw_projects` (`CurrentDrivableActor_endpoints.json`, `DriverAid_endpoints.json`,
`Player_endpoints.json`) + probe actual.
En Lua se llaman igual que en HTTP: `drivableActor:HUD_Get*(…)` y
`playerController:GetDriverAidData(…)`.

**No hace falta ejecutar el juego** para este inventario. **Sí hace falta** una sesión corta por
tipo de tren para saber qué funciones devuelven `IsActive=true` vs vacío/inactivo (cada locomotora
implementa un subconjunto).

### Ya en el probe (~17 Hz)

| Campo IPC | Lua | Uso autopiloto |
| --- | --- | --- |
| `speed_ms` | `HUD_GetSpeed` | ✅ **congelado** — GUI ~20 Hz, sin caché |
| `power` / `handle_notch` | `HUD_GetPowerHandle` | ✅ mandos UK |
| `train_brake` | `HUD_GetTrainBrakeHandle` | ✅ freight + UK |
| `loco_brake` | `HUD_GetLocomotiveBrakeHandle` | ✅ freight |
| `dyn_brake` | `HUD_GetElectricBrakeHandle` | ✅ EMU / diesel dyn |
| `accel_ms2` | `HUD_GetAcceleration` | ✅ learner |
| `max_speed_ms` | `HUD_GetMaxPermittedSpeed` | ATS / límite tren |
| `speed_limit_ms` | `GetDriverAidData.SpeedLimit` | ✅ límite vía |
| `gradient_pct` | `GetDriverAidData` → `gradient` | ✅ learner / distancia freno |
| `vehicle` | `GetClass():GetFName()` | layout combined/freight |

### Prioridad alta — añadir al probe (frenado / física)

| Dato | Lua (`drivableActor`) | Para qué |
| --- | --- | --- |
| Patinaje | `HUD_GetIsSlipping` | Reducir tracción / no confiar en acel |
| Bloqueo tracción | `HUD_GetIsTractionLocked` | No acelerar si locked |
| Esfuerzo tracción | `HUD_GetTractiveEffort` | Validar perfil vs real |
| Esfuerzo freno (HUD) | `HUD_GetTractiveEffort` (campo `BrakeEffort (N)`) | Correlación decel real |
| Manómetros aire | `HUD_GetBrakeGauge_1` / `_2` | Presión freno (Pa), UK/NA según cabina |
| Estado frenos (interno) | `IS_GetBrakeState` | Aplicado/liberado/parking (IDs por tren) |
| Demanda freno penalización | `GetPenaltyBrakeDemand` | Seguridad / no luchar contra PTC |
| Esfuerzo objetivo IS | `IS_GetTargetTractiveEffortN` / `IS_GetTargetBrakingEffortN` | Lo que pide la simulación |
| Dirección | `HUD_GetDirection` | Reverser / marcha |
| Amperímetro | `HUD_GetAmmeter` | EMU / diesel eléctrico (no es mando) |

### Prioridad media — planning y vía (`playerController` / `DriverAid`)

| Dato | API | Para qué |
| --- | --- | --- |
| `distanceToNextSpeedLimit` | `GetDriverAidData` → probe | ✅ ~20 Hz |
| `nextSpeedLimits[]` | idem (2 primeros) | ✅ |
| `distanceToSignal` / `nextSignals[]` | idem | **🎯 siguiente** — `signal_brake` v2 (hoy stub) |
| `formationMaxSpeed` / `trackMaxSpeed` | idem | Techo real del consist |
| Perfil altura vía | `DriverAid.TrackData` | Curvas / túneles (futuro) |

### Por tipo de tren — solo si `IsActive` / no cero

| Familia | Funciones HUD extra | Notas |
| --- | --- | --- |
| **EMU UK** (323) | `HUD_GetAmmeter`, gauges 1–2 | Handle combinado; dyn a veces 0 |
| **Diesel NA** (SD40) | `HUD_GetEngineRPM`, 4 mandos separados | Sin `HUD_GetPowerHandle` UK; usar ejes brake |
| **EMU moderno** | `HUD_GetElectricBrakeHandle`, regen (`bRegenBrakeAC` prop) | Freno rheostático |
| **Vapor** | `HUD_GetSteamBoilerPressure`, `…ChestPressure`, `…WaterLevel`, `…CoalBunker`, `…ReverserCutoff` | No prioritario autopiloto |
| **Transmission** | `HUD_GetGearIndex` | Algunos DMUs |

### Simulación / consist (poll lento o al cargar escena)

| Dato | Ruta HTTP / Lua | Para qué |
| --- | --- | --- |
| Masa carga | `RailVehiclePhysicsComponent0.GetMassOfCargo` | Inercia / distancia freno |
| Longitud formación | `GetFormationLength` | — |
| Longitud entre acopladores | `GetLengthBetweenCouplers` | — |
| Coef. esfuerzo/freno | `GetSimpleEffortOrBrakeCoefficient` | Modelo físico nativo |
| Presión cilindro freno | `Simulation_BrakeCylinder_*_Pressure` | Diagnóstico aire |
| Compresor | `Simulation_AirCompressor_IsCompressing` | Frenos listos |
| Gradiente por eje | `Simulation/Axle_*_*.TrackGradient_DEG` | Alternativa a DriverAid |

### Puertas — baja prioridad autopiloto

| Dato | API | Notas |
| --- | --- | --- |
| ¿Puede abrir puertas? | `CanOperateDoors` / `CanOperatePassengerDoors` | Parada en andén |
| Estado puerta | `PassengerDoor_*` (muchas rutas por vehículo) | Varía por carro |
| Bloqueo selectivo | `bSelectiveDoorLocked` | — |

No necesarios para frenar; sí para escenarios de servicio comercial.

### Descubrimiento por tren (sesión en juego, ~5 min)

1. Cabina + **F8** con probe actual (anotar qué sale `?`).
2. Con `-HTTPAPI`: `python tsw_monitor.py --explore` (lista `Function.HUD_*` del actor actual).
3. Rellenar tabla por vehículo:

| Vehículo | HUD activos | Mandos | Gradiente OK | Notas |
| --- | --- | --- | --- | --- |
| Class 323 | speed, mandos, acel, límite, grad | combined 0–8 | ✅ | `gradient` vía `GetDriverAidData` |
| BNSF SD40-2 | … | 4 ejes | ? | pendiente sesión A3 |

**Sesión en juego pendiente:** rellenar fila SD40-2 y decidir qué campos extra van al probe v2.

---

### B1. Mod lectura — ✅ (`TelemetryProbeMod`)

- [x] `mods/TelemetryProbeMod/Scripts/main.lua` — hook `ReceiveTick`, solo lectura
- [x] Escribe `GetData.txt` ~20 Hz
- [x] `install_ue4ss_probe.bat` + línea en `mods.txt`
- [ ] Renombrar a `TelemetryBridgeMod` (opcional, cosmético)
- [ ] Flag “autopilot armed” al salir (patrón Dastsc) — B4

### B2. Reader Python — ✅

- [x] `tsw_ue4ss_reader.py` — parser + monitor + `--benchmark` + `--api` (comparar grad)
- [x] Tests unitarios (`test_tsw_ue4ss_reader.py`)
- [ ] Benchmark formal vs `tsw_fast_telemetry` en misma sesión

### B3. Integración — ✅ (autopilot operativo; planning híbrido)

- [x] `tsw_telemetry_source.py` — preferencia `ue4ss`, fallback `tsw_api`
- [x] `learn_monitor.py` / `tsw_autopilot.py` / `handle_controller.py`
- [x] `aprender.bat` conecta en modo UE4SS
- [x] `gradient_pct` en probe (`GetDriverAidData.Gradient`) + fallback HTTP `DriverAid.Data`
- [x] Documentar en [GUIA.md](GUIA.md)
- [x] `autopilot_core.py` + `autopilot_gui.py` — bucle 20 Hz, GUI en hilo aparte
- [x] **Velocidad actual** — congelada; tests regresión `test_speed_*`
- [x] Planning HTTP: `next_limit` + cola 2 límites + odometría entre polls
- [x] Frenado P1 v2: `BrakeCoordinatorV2` + perfil decel por muesca (`OnlineLearner`)
- [x] **Ejecución Dastsc P1** — `v2/command.py` + notch IPC directo

  ([DASTSC_PARITY.md](DASTSC_PARITY.md))

- [x] Modo **solo frenado** (sin acelerador automático)
- [x] Planning en probe Lua (`distanceToNextSpeedLimit` / 2 límites @ ~20 Hz)
- [x] **Horario HUD** — `hud_timetable.py`, `tsw_hud.db`, filtro paradas, `car_stop_signs`

### B4. Escritura sin HTTPAPI — ✅ (mandos vía SendCommand.txt)

- [x] Mod Lua lee `%TEMP%\TSW6Bridge\SendCommand.txt` (allowlist como `tsw_command_bus`)
- [x] Python escribe líneas `PowerBrakeHandle:0.62` en lugar de PATCH (preferido si probe activo)
- [x] Purga al cerrar autopilot (mandos neutros + flag)
- [x] Autopiloto **sin `-HTTPAPI`** si probe UE4SS activo (planning sigue opcional vía HTTP)

**Planning:** sin `-HTTPAPI` no hay cola de 2 límites HTTP; opcional probe v2 con distancias.

**Opcional antes de B4 (mejora planning, no sustituye mandos):** probe v2 con
`distanceToNextSpeedLimit` en `GetData.txt`.

---

## Criterios MVP

| # | Criterio | Estado |
| --- | --- | --- |
| 1 | ≥15 Hz `speed_ms` + mando en Python | ✅ congelado 2026-08-22 |
| 2 | Valores Lua ≈ HTTPAPI misma sesión | ✅ 323 |
| 3 | `aprender.bat` sin RailBridge | ✅ |
| 3b | Autopiloto frenado P1 v2 (límite + estación + prioridad) | ✅ |
| 4 | Sin mandos colgados al cerrar Python | ✅ (neutro + purga IPC) |
| 5 | Autopiloto sin `-HTTPAPI` | ✅ (mandos; planning HTTP opcional) |

---

## Referencias rápidas

| Recurso | Ruta |
| --- | --- |
| Mod probe (repo) | `mods/TelemetryProbeMod/Scripts/main.lua` |
| IPC lectura | `%TEMP%\TSW6Bridge\GetData.txt` |
| IPC escritura | `%TEMP%\TSW6Bridge\SendCommand.txt` + `TSW6ApplyCommands.flag` |
| `mods.txt` juego | `...\Binaries\Win64\Mods\mods.txt` |
| Log UE4SS | `...\Binaries\Win64\UE4SS.log` |
| Endpoints HTTP gradiente | `...\tsw_api_reader\endpoints\DriverAid_endpoints.json` |
| Patrón Dastsc | `C:\Users\doski\Dastsc\docs\GUIA_TECNICA_IPC.md` |

---

## Bitácora

| Fecha | Qué | Resultado |
| --- | --- | --- |
| 2026-06-13 | A1 instalación | UE4SS en Steam Win64 |
| 2026-08-17 | A2 DynamicHUD | F5/F6 OK en cabina |
| 2026-08-18 | A3 probe | ~17 Hz Class 323; power 0–8 |
| 2026-08-18 | B3 integración | `tsw_telemetry_source`, aprender UE4SS |
| 2026-08-18 | HUD | `enabled.txt` anulaba `mods.txt : 0`; borrado; HUD normal |
| 2026-08-18 | Gradiente | `gradient_pct` en probe vía `driverAid.gradient`; 323 validado in-game |
| 2026-08-18 | probe bat | Restaurado `--benchmark` en `tsw_ue4ss_reader.py` |
| 2026-08-19 | Autopilot | Solo frenado; P1 Dastsc; GUI 10 Hz |
| 2026-08-19 | Planning | Cola 2 límites; odometría dist HTTP; decel/muesca en perfil JSON |
| 2026-08-19 | Learner | Freno muescas 0–3 siempre; tracción con `--learn` |

| 2026-08-19 | B4 IPC | SendCommand.txt + flag; mandos sin -HTTPAPI |

| 2026-08-19 | Probe v2 | 2 límites en GetData.txt; planning sin HTTP |
| 2026-08-22 | Velocidad | Congelada: probe directo ~20 Hz GUI; tests regresión; planning aparte |
| 2026-08-23 | HUD horario | `tsw_hud.db`, filtro paradas, `car_stop_signs`, merge `hud_geo`; SQLite thread-local |
| 2026-08-24 | Frenado P1 v2 | `BrakeCoordinatorV2` en autopilot; tests coordinator |
| 2026-08-24 | Consolidación frenado | Todo en `braking/v2/`; eliminado `archive/braking_v1/` |
| 2026-08-24 | Horario GUI | arr/dep y tabla paradas validados in-game (2R17 / Cross-City) |
| 2026-08-24 | Mandos solo IPC | P1/P2/reset: IPC absoluto primero; teclado solo fallback |
| 2026-08-24 | RELEASE unified | Coordinator: soltar en cartel + coast; tests coordinator |
| 2026-08-24 | `station_eta` | `next_stop_arrival` → planner; parser `HH:MM:SS` |
| 2026-08-24 | Log v2 | `thr`, `gap`, `wd`, `p1eta` en ciclo; guía en sección P1 v2 arriba |

---

## Mandos: IPC vs teclado

| Vía | Cuándo | Fiabilidad |
| --- | --- | --- |
| **IPC** (`SendCommand.txt` → Lua) | **Siempre primero** si `mandos=ipc` (P1 B1–B3, RELEASE, P2) | ✅ **Por defecto** — notch absoluto 0–8 en un ciclo (~120 ms) |
| **Teclado** (A/D, pulso 120 ms) | Solo si IPC falla 5 veces (penalización 5 min) o sin bridge | ⚠️ Fallback; riesgo de saltar neutro |
| **HTTP PATCH** | Fallback legacy si no hay UE4SS | Más lento (50–150 ms); requiere `-HTTPAPI` |

Con `mandos=ipc` en el heartbeat del autopilot, **todos** los mandos van por
`PowerBrakeHandle` absoluto. El teclado solo entra si IPC falla repetidamente.

Detalle: `handle_controller.py` (`prefer_absolute` en RELEASE/COAST_THROTTLE) · `tsw_ipc_bus.py`.

## Próximo paso (orden fijo)

1. **Validar in-game** — 2R17 Cross-City: cartel+andén, `uni=Y`, `gap=`, RELEASE @55, `p1eta=`.

   Horario GUI ✅.

2. **Telemetría señal** — probe o HTTP: `distanceToSignal` + aspecto → `TrainState` →

   `signal_brake`.

3. **Tablón OCR/GPS** — cablear distancia fina a `station_brake` / coordinador.
4. **Sesión A4** — estabilidad probe 10+ min (cuando 1–3 OK).
5. **SD40-2** — probe freight + [FREIGHT_NA.md](FREIGHT_NA.md) (después de UK cerrado).

**No retocar** pipeline velocidad sin tests: `test_brake_v2.py` + `test_brake_coordinator.py` +
`test_speed_decider.py`.
