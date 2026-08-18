# Pendiente — DynamicHUD v1.0.0 → TelemetryBridge

**Objetivo:** telemetría **in-process** (~17–20 Hz) vía UE4SS y puente a Python (`GetData.txt`).

**Estado:** ✅ MVP Class 323 (2026-08-18) — lectura UE4SS integrada · escritura aún HTTPAPI · SD40-2
pendiente
**Paquete UE4SS:** `C:\Users\doski\Desktop\investigacion tsw 6\DynamicHUD v1.0.0`
**Relacionado:** [ARQUITECTURA.md](ARQUITECTURA.md) · [FREIGHT_NA.md](FREIGHT_NA.md) ·
[GUIA.md](GUIA.md)

---

## Lectura vs escritura (importante)

| Capa | Fuente actual | ¿Requiere `-HTTPAPI`? |
| --- | --- | --- |
| **Lectura** (velocidad, mandos, acel) | `TelemetryProbeMod` → `GetData.txt` | **No** |
| **Escritura** (autopiloto mueve mandos) | `tsw_command_bus` → PATCH `localhost:31270` | **Sí** |
| **Calibración** (`aprender.bat`) | Solo lectura | **No** (con probe activo) |
| **Autopiloto** (`iniciar_autopilot.bat`) | Lectura UE4SS + escritura HTTP | **Sí** (hoy) |

**Conclusión:** el objetivo final es **no depender de HTTPAPI** (patrón Dastsc: `GetData.txt` +
`SendCommand.txt` en Lua).
Hoy solo hemos migrado la **lectura**. La **escritura in-process** es la fase **B4** — sin ella el
autopiloto sigue necesitando `-HTTPAPI` aunque la telemetría venga del probe.

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
| planning (estaciones, next limit) | — | limitado | no en probe |

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

## Gradiente y planning

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

Alternativa por eje (simulación):

```http
```

### Planning (estaciones, next limit)

Solo existía en RailBridge (`companion_dmi_planning_delta`). HTTPAPI tiene señales/distancias en
`DriverAid.Data` pero no el route monitor completo. **No bloquea** calibración ni autopiloto básico
por límite actual.

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
| `speed_ms` | `HUD_GetSpeed` | ✅ núcleo |
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
| `distanceToNextSpeedLimit` | idem | Frenado anticipatorio |
| `nextSpeedLimits[]` | idem | Cambios de límite adelante |
| `distanceToSignal` / `nextSignals[]` | idem | Señales (menos crítico offline) |
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

### B3. Integración — ✅ parcial

- [x] `tsw_telemetry_source.py` — preferencia `ue4ss`, fallback `tsw_api`
- [x] `learn_monitor.py` / `tsw_autopilot.py` / `handle_controller.py`
- [x] `aprender.bat` conecta en modo UE4SS
- [x] `gradient_pct` en probe (`GetDriverAidData.Gradient`) + fallback HTTP `DriverAid.Data`
- [x] Documentar en [GUIA.md](GUIA.md)

### B4. Escritura sin HTTPAPI — ⬜ siguiente hito técnico

- [ ] Mod Lua lee `%TEMP%\TSW6Bridge\SendCommand.txt` (allowlist como `tsw_command_bus`)
- [ ] Python escribe líneas `PowerBrakeHandle:0.62` en lugar de PATCH
- [ ] Purga al cerrar autopiloto (mandos neutros)
- [ ] Entonces **solo UE4SS** — sin `-HTTPAPI`

Hasta B4: arrancar TSW con **`-HTTPAPI`** para `iniciar_autopilot.bat`.

---

## Criterios MVP

| # | Criterio | Estado |
| --- | --- | --- |
| 1 | ≥15 Hz `speed_ms` + mando en Python | ✅ |
| 2 | Valores Lua ≈ HTTPAPI misma sesión | ✅ 323 |
| 3 | `aprender.bat` sin RailBridge | ✅ |
| 4 | Sin mandos colgados al cerrar Python | ⬜ (depende HTTPAPI hoy) |
| 5 | Autopiloto sin `-HTTPAPI` | ⬜ B4 |

---

## Referencias rápidas

| Recurso | Ruta |
| --- | --- |
| Mod probe (repo) | `mods/TelemetryProbeMod/Scripts/main.lua` |
| IPC lectura | `%TEMP%\TSW6Bridge\GetData.txt` |
| IPC escritura (futuro) | `%TEMP%\TSW6Bridge\SendCommand.txt` |
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

---

## Próximo paso

1. **Usuario:** sesión estabilidad 10+ min (A4) cuando puedas.
2. **Código:** B4 `SendCommand.txt` para quitar `-HTTPAPI` del autopiloto.
3. **Después:** SD40-2 en probe (A3 freight) + fases FREIGHT_NA 4–6.
