# Plan ApiExplorerMod — laboratorio Lua (HTTP ↔ UE)

**Fecha:** 2026-08-30  
**Estado:** L0.1–L0.6c validados in-game (323) · L0.7–L0.8 pendiente · build `20260830l`  
**Sesión referencia:** [`data/lab_exports/exports/20260830T213100Z/`](../../data/lab_exports/exports/20260830T213100Z/)  
**Plan maestro:** [PLAN_V2.md](PLAN_V2.md) · **Probe producción:** [PENDIENTE_DYNAMICHUD.md](../v1/PENDIENTE_DYNAMICHUD.md)  
**Captura F5:** [LAB_CAPTURA_F5.md](LAB_CAPTURA_F5.md)  
**Referencias API:** [TSW_HTTPAPI_INDEX.md](../reference/TSW_HTTPAPI_INDEX.md) ·
[CURRENTFORMATION_API.md](../reference/CURRENTFORMATION_API.md) ·
[DRIVERAID_API.md](../reference/DRIVERAID_API.md) · [DRIVERINPUT_API.md](../reference/DRIVERINPUT_API.md)  
**Dumps HTTP (RailBridge):** `Desktop\investigacion tsw 6\apis\` — válidos; mismos nombres que Lua/HTTPAPI

---

## Resumen

`TelemetryProbeMod` (~2000 líneas) mezcla **canal de producción** (GetData ~20 Hz, IPC mandos) con
**laboratorio** (F9, reflect, dump palancas). Eso dificulta depurar el probe y hace caro cada campo
nuevo en GetData.

**ApiExplorerMod** es un **segundo mod UE4SS**, escrito desde cero, solo para:

- **explorar** qué expone cada tren en **Lua** (actor drivable, DriverAid, componentes) — aunque no
  vaya al probe ni al autopilot;
- correlacionar con rutas **HTTPAPI** (`-HTTPAPI`, puerto 31270) cuando haga falta validar;
- alimentar el **paquete G-B** (`data/vehicles/<id>.json`) y las tarjetas C1/C2/lim2 del plan v2.

**No** escribe `GetData.txt`, **no** aplica mandos, **no** comparte hook de tick con el probe.

### Explorar ≠ usar todo

Cada locomotora / EMU / consist tiene **otra cabina**: otros nombres de palanca, otro `HUD_Get*`,
otro `Simulation`, mandos que en el 323 no existen (cruise, din independiente, MCB, …). El explorer
existe para **descubrir** eso en una sesión de cabina y dejar constancia en JSON — no para meter cada
campo en GetData.

| Destino del dato | Quién decide | Ejemplo 323 |
| --- | --- | --- |
| **Producción** (~20 Hz) | Revisión humana + D2 → probe | `speed_ms`, `gradient_pct`, `PowerBrakeHandle` |
| **Paquete G-B** | L0.7 desde `controls.json` | `layout_hint: combined`, mapa muescas PBH |
| **Catálogo / referencia** | Se guarda en export; no se cablea | `HUD_GetAmmeter`, gauges, `RegenBrakes` |
| **Otro tren** | Nueva sesión F5–F7 en esa cabina | SD40: palancas split, sin PBH UK |

**323 y F5:** en la sesión referencia ya están los **16/16 `HUD_Get*`** sin errores. Para el 323 no
hace falta seguir puliendo F5 salvo protocolo multi-captura (frenar/acelerar) si se estudia física.
El valor del mod **crece con cada tren nuevo**, no con repetir el mismo snapshot.

---

## Alineación con PLAN_V2

| Concepto v2 | Rol del explorer |
| --- | --- |
| §4.1 probe solo I/O | Explorer fuera del hot path de producción |
| §1 G-B paquete tren | Salida → borrador `data/vehicles/<id>.json` |
| C1 señales (`signal_red`, `signal_dist_cm`) | Modo `driver_aid` frente a semáforo rojo |
| C2 andén (`station_dist_cm`) | Modo `driver_aid` en APPROACHING |
| lim2 / TArray | Modo explícito con tope de profundidad |
| D2 schema GetData | Explorer **propone** claves; probe las adopta en PR atómico |
| D1 agente `agent/` | Correlator Python = herramienta aparte, no en `agent/` |
| F9 / `pairs` en probe | Migrar aquí; probe pierde ~300–500 líneas cuando se valide |

**Regla de oro:**

```text
investigación (explorer) → JSON + manifest → revisión humana
  → paquete tren o CANAL_CONTROL → extract_* mínimo en probe
```

---

## Estrategia Lua vs HTTP (decisión 2026-08-30)

Los nombres HTTP y Lua **describen el mismo árbol UE** (`DriverAid.Data`, `HUD_GetSpeed`,
`DriverInput/PowerBrakeHandle`). No es copiar el path HTTP en Lua: hay que saber si es `UFunction`,
propiedad del actor o struct `GetDriverAidData`.

| Capa | Canal | Frecuencia | Qué cubre |
| --- | --- | --- | --- |
| **Rápido (producción)** | Probe Lua → `GetData.txt` + IPC | ~20 Hz | HUD, DriverAid escalares, odo, cilindro |
| **Lento (planning)** | HTTP Python | ~2 s | `DriverAid.TrackData`, horario HUD, masa formación |
| **Laboratorio** | ApiExplorer F5–F7 | al pulsar tecla | Validar lectura Lua; proponer claves D2 |
| **Catálogo** | RailBridge JSON (Desktop) | una vez | Esquema, `writable`, peldaños — no runtime |

**Objetivo v2:** el autopilot **no depende de HTTP en el tick**. HTTP queda para datos voluminosos o
poco urgentes (`TrackData.markers`, correlación ocasional). El explorer demuestra qué se puede leer
en Lua; el probe adopta solo lo aprobado (D2).

**Log al circular:** el explorer **no** hace log continuo (~20 Hz = probe). Para ver si un campo
cambia al frenar/acelerar: varias capturas F5/F7 con nombre distinto (ver
[LAB_CAPTURA_F5.md](LAB_CAPTURA_F5.md)) o `probe_ue4ss_log.bat`. Campos que varíen y aporten → clave
nueva en `GetData`.

---

## Principios de diseño

1. **Cero mezcla** con `mods/TelemetryProbeMod/` — carpeta, puente y responsabilidades distintas.
2. **Sin trabajo en hot path** — no `ReceiveTick` pesado; capturas por tecla o comando manual.
3. **Módulos pequeños** — ningún archivo >300 líneas; composición por `require`.
4. **Salida estructurada** — JSON con schema versionado, no solo `print` al log UE4SS.
5. **Seguro por defecto** — profundidad máxima, `pcall` en cada lectura; reflect profundo opt-in.
   **Nunca** `GetClass` / `ForEachProperty` / `ForEachFunction` / `GetFullName` sobre UObject con
   `IsValid() == false` (crash nativo UE4SS — ver § reflect Simulation, build `20260830k`).
6. **Un mod de producción** — con autopilot activo: solo `TelemetryProbeMod`; explorer desactivado
   en la lista de mods UE4SS.
7. **Una sesión por vehículo** — carpeta `exports/<timestamp>/` con `vehicle_class` en manifest; no
   mezclar trenes en el mismo JSON.

---

## Arquitectura

```text
┌─ UNA VEZ / bajo demanda (ApiExplorerMod) ─────────────────────────────────┐
│  F5–F7 (+ Shift) → modo captura                                           │
│  GetDrivableActor + GetDriverAidData + reflect controlado                 │
│  ESCRIBE data/lab_exports/exports/<session>/<mode>.json (repo)            │
│  NO toca %TEMP%\TSW6Bridge\ · NO SendCommand · NO GetData.txt             │
└───────────────────────────────────────────────────────────────────────────┘
         │ JSON + manifest
         ▼
┌─ Python laboratorio (opcional) ────────────────────────────────────────────┐
│  scripts/tools/api_correlator.py                                          │
│  GET http://127.0.0.1:31270/get/... (mismo instante ±500 ms)            │
│  Cruza: http_path ↔ lua_path ↔ value                                      │
└───────────────────────────────────────────────────────────────────────────┘
         │ revisión humana
         ▼
┌─ Artefactos v2 ─────────────────────────────────────────────────────────────┐
│  data/vehicles/class_323.json  (G-B)                                      │
│  docs/reference/*.md  (columna Lua actualizada)                           │
│  CANAL_CONTROL.md + extract_* en probe (solo campos aprobados, D2)        │
└───────────────────────────────────────────────────────────────────────────┘
```

### Árbol del mod (objetivo ~800–1200 líneas total)

```text
mods/ApiExplorerMod/
  Scripts/
    main.lua           # carga, teclas, banner build (~80 líneas)
    config.lua         # rutas, límites, profundidad, allowlist
    bridge.lua         # escritura JSON + manifest de sesión
    context.lua        # controller, drivable, vehicle id, timestamp
    serialize.lua      # número/string/bool/struct → JSON seguro
    reflect.lua        # ForEachProperty/Function con tope
    hud_batch.lua      # HUD_Get* (equivalente HTTP Function.*)
    controls.lua       # inventario palancas + Notches (estilo wizard Dastsc)
    driver_aid.lua     # escalares DriverAid (C1/C2/lim2 candidatos)
    formation.lua      # Simulation, masa, cilindros, slip
    modes.lua          # orquesta modos; una función por tecla
```

**No** copiar bloques del probe: reutilizar **patrones** (`pcall`, `unwrap_number`,
`ForEachProperty`), no pegar `main.lua`.

---

## Puente y contrato de salida

| | Probe (producción) | Explorer (laboratorio) |
| --- | --- | --- |
| Carpeta | `%TEMP%\TSW6Bridge\` | `data/lab_exports/` en el repo (vía `lab_root.txt`) |
| Formato | TSV una línea `GetData.txt` | JSON por captura en `exports/<session>/` |
| Frecuencia | ~20 Hz | Solo al pulsar tecla |
| Consumidor | `tsw_ue4ss_reader.py` | humano + `api_correlator.py` |

### Manifest de sesión (`session.json`)

```json
{
  "schema": "tsw6-lab-export/1",
  "build": "20260830a",
  "vehicle_class": "BP_Train_323_C",
  "route_hint": "Cross-City",
  "httpapi": true,
  "modes_run": ["hud_batch", "controls", "driver_aid"]
}
```

### Ejemplo `hud_batch.json`

```json
{
  "mode": "hud_batch",
  "lua": {
    "HUD_GetSpeed": { "Speed (ms)": 12.4 },
    "HUD_GetTrainBrakeHandle": { "HandlePosition": 0.33 }
  },
  "http_guess": {
    "CurrentFormation/0/Function.HUD_GetSpeed": 12.4,
    "CurrentFormation/0/Function.HUD_GetTrainBrakeHandle": { "HandlePosition": 0.33 }
  }
}
```

`http_guess` se rellena en Lua con reglas de mapeo conocidas; `api_correlator.py` valida contra
GET real.

---

## Modos de captura (teclas propuestas)

| Tecla | Modo | Para qué (v2) | HTTP relacionado |
| --- | --- | --- | --- |
| **F5** | `hud_batch` | Telemetría cabina (probe hoy) | `Function.HUD_Get*` |
| **F6** | `controls` | Paquete G-B: nombres lever, Notches | `DriverInput/*` |
| **F7** | `driver_aid` | C1 señal, C2 andén, lim2 candidatos | `DriverAid.*` |
| **Shift+F5** | `formation` | Masa, cilindros, slip, adherencia | `CurrentFormation/0/Simulation/*` |
| **Shift+F6** | `reflect_shallow` | Props/funcs drivable + árbol `Simulation` (solo nodos válidos) | — |
| **Shift+F7** | `correlate_tick` | Timestamp para burst HTTP en Python | árbol completo |

**No usar F10–F12** si `ConsoleEnablerMod : 1` — F10 abre la **consola UE** (ver log:
`[ConsoleEnabler] ConsoleKey[1]: F10`). Con probe ON, F7–F9 son del TelemetryProbeMod.

Sin hook de `ReceiveTick` en producción: solo `RegisterKeyBind`. Banner al cargar escenario:
`[ApiExplorer] F5 HUD · F6 controls · F7 DriverAid`.

**No hay menú en pantalla** — las capturas son con **F5–F7 en cabina** (escenario cargado, dentro del
tren). Comprobar carga en `UE4SS.log`: línea `[ApiExplorer] Mod loaded`.

Instalación: `install_ue4ss_explorer.bat` en la raíz del repo (no copiar solo el `.bat` sin `mods/`).

### Protocolo sesión completa (cualquier tren)

1. Cabina cargada, probe **OFF**, explorer **ON**.
2. Pulsar en orden (o el subconjunto que interese): **F5 → F6 → F7** · opcional **Shift+F5/F6/F7**.
3. Carpeta `data/lab_exports/exports/<session>/` queda con `session.json` + un JSON por modo.
4. Anotar ruta / escenario en `notas_sesion.md` (opcional) si vas a comparar trenes.
5. **No** hace falta HTTP en cabina para explorar Lua; correlator (L0.5) es opcional después.

Para **323** una pasada F5–F7 ya cubre cabina HUD + mandos + DriverAid escalares (ver bitácora).

---

## Logs

| Canal | Qué registra | Estado |
| --- | --- | --- |
| **UE4SS.log** | `[ApiExplorer]` al cargar, cada captura, errores (`skip`, `ERROR writing`) | ✅ implementado |
| **`data/lab_exports/exports/<session>/`** | `session.json`, `<mode>.json` | ✅ (puntero en `Documents\TSW6\lab_root.txt`) |
| **`logs/api_explorer_*.txt`** (repo) | Volcado opcional de UE4SS.log filtrado por `[ApiExplorer]` | ⬜ L0.8 — script `probe_ue4ss_log.bat` análogo |
| **Python correlator** | `correlation_report.md` en la misma carpeta de sesión | ✅ L0.5 |

**No** hay log continuo ~20 Hz (eso es del probe en `GetData.txt`). El explorer solo escribe al pulsar
tecla. Para sesión de laboratorio: guardar UE4SS.log tras F5–F7 o copiar la carpeta `exports\`.
Ver protocolo multi-captura en [LAB_CAPTURA_F5.md](LAB_CAPTURA_F5.md).

---

## Tests

Separados del probe (D7 / `parse_probe_line`). El explorer valida **exports JSON**, no el juego en CI.

| Nivel | Qué | Cuándo | Estado |
| --- | --- | --- | --- |
| **In-game** | L0.2: `hud_batch.json` 16/16 sin `errors[]` | 323 sesión referencia | ✅ `20260830T145544Z` |
| **In-game** | L0.3: `controls.json` con levers + `layout_hint` | 323 F6 sin freeze | ✅ misma sesión |
| **In-game** | L0.4: `driver_aid.json` escalares | 323 F7; arrays TArray pendientes | 🟡 parcial |
| **Fixture pytest** | `tests/fixtures/lab/hud_batch_323.json` + parser | Tras primera captura real | ⬜ L0.8 |
| **Unit** | `tests/test_lab_serialize.py` — round-trip JSON Lua-like | Sin juego | ⬜ L0.8 |
| **Compare script** | `compare_lab_controls.py` — `layout_hint` vs `detect_control_layout` | JSON en disco | ✅ L0.3 |
| **Correlator** | `api_correlator.py` — HTTP vs `http_guess` | `-HTTPAPI` + export en disco | ✅ pytest mock; live con juego |
| **Compare script** | `compare_lab_vs_probe.py` — `hud_batch` vs línea GetData | Dos archivos en disco | ⬜ L0.8 |

**Regla:** los tests del autopilot (`test_ue4ss_reader`, etc.) **no** dependen del explorer. Si el
probe está OFF, no hay GetData — el compare in-game solo tiene sentido con **ambos mods** en la misma
sesión de validación (o dos capturas exportadas).

---

## Coexistencia con TelemetryProbeMod

Matriz recomendada (`mods.txt`):

| TelemetryProbeMod | ApiExplorerMod | Uso | ¿Interfiere? |
| --- | --- | --- | --- |
| **: 1** | **: 0** | Autopilot / calibración / producción | — (modo normal) |
| **: 0** | **: 1** | Solo laboratorio en cabina | **No** — es el modo previsto para explorar |
| **: 1** | **: 1** | Validar L0.2 (comparar HUD) | **Casi no** — ver abajo |
| **: 0** | **: 0** | Jugar sin mods TSW6 | — |

### Si desactivas el probe principal (`TelemetryProbeMod : 0`)

**No hay interferencia técnica** con el explorer:

- Rutas distintas: `TSW6Bridge\` (probe) vs `TSW6Lab\` (explorer).
- El explorer **no** escribe `GetData.txt`, **no** lee `SendCommand.txt`, **no** registra
  `ReceiveTick`.
- Teclas distintas con probe ON: probe F7/F8/F9 · explorer F5–F7 (+ Shift). **Sesión lab:** probe OFF.

**Sí pierdes** (esperado):

- Autopilot, calibración learner, `probe_ue4ss.bat`, GUI que lee GetData.
- La validación L0.2 “igual que GetData” — necesitas una sesión con probe ON o un `GetData.txt`
  guardado de antes.

### Si ambos están activos (`: 1` / `: 1`)

Permitido para **comparar** HUD en la misma partida. Riesgos menores:

| Riesgo | Gravedad | Mitigación |
| --- | --- | --- |
| Dos `RegisterInitGameStatePostHook` | Baja | Cada uno resetea su puente; no comparten estado |
| Carga CPU (probe ~20 Hz) | Baja | Explorer solo al pulsar tecla |
| Confusión de teclas / logs | Media | Prefijos `[TelemetryProbe]` vs `[ApiExplorer]` |
| `reflect_shallow` / futuro `controls` con `FindAllOf` | Media | No pulsar en pleno tick si el juego va justo; preferir tren parado |
| `reflect_shallow` sobre hijos `Simulation` inválidos (`IsValid=false`) | **Alta** | Build `j` crasheó TSW (`ACCESS_VIOLATION` en UE4SS). Build **`k`+**: solo stub si `index_ok` y no `IsValid`; sin `ForEach*` |

**Recomendación:** sesión de laboratorio = **solo explorer ON**. Sesión de autopilot = **solo probe
ON**. La excepción es la validación puntual L0.2.

### Reinicio

UE4SS **no recarga Lua en caliente**. Tras cambiar `mods.txt`, reinicia TSW6.

---

## Mapeo HTTP ↔ Lua

Tabla interna (`config.lua`); ampliar con cada sesión validada.

| Patrón HTTP | Acceso Lua típico |
| --- | --- |
| `CurrentFormation/0/Function.HUD_GetX` | `actor:HUD_GetX(out)` |
| `CurrentFormation/0/PowerBrakeHandle.InputValue` | `actor.PowerBrakeHandle.InputValue` |
| `CurrentFormation/0/Simulation/BrakeCylinder_2_1.Pressure_BAR` | hijo `Simulation` → componente por nombre |
| `DriverAid.Data` / `DriverAid.distanceToSignal` | `controller:GetDriverAidData(table)` |
| `DriverAid.TrackData` | **solo HTTP** hoy (~2 s en Python) |
| `DriverInput/PowerBrakeHandle.InputValue` | `GetDrivableActor().PowerBrakeHandle` |

Si el nombre no coincide: el correlator marca `match: "fuzzy"` cuando el valor numérico coincide en
±ε.

---

## Analogía Dastsc (profile wizard)

`nexus-profile-wizard.py` (Dastsc) lee **RailDriver** (`GetControllerValue`) en Train Simulator
Classic — **no** es un explorador HTTP. El equivalente TSW6:

| Dastsc | ApiExplorerMod |
| --- | --- |
| `GetControllerValue(id)` | `lever.InputValue` / `HUD_Get*` |
| Captura muesca a muesca | Modo `controls` + wizard Python opcional (fase L6) |
| `notches_throttle_brake` en perfil | `notch_map` en `data/vehicles/*.json` |
| Un tren por sesión | `vehicle_class` en manifest |

**Fase L5–L6:** JSON + revisión manual primero; GUI Python después si hace falta.

---

## Relación con el probe actual

| Fase | Probe | Explorer |
| --- | --- | --- |
| **Paralelo** | Sigue con F9 embebido | Mod nuevo; comparar salidas |
| **Tras validar 323** | Quitar F9/reflect (−300–500 líneas) | Fuente única de dumps |
| **Al cablear C1** | Solo `extract_signal_red()` (~15 líneas) | Nombres ya en `driver_aid.json` |
| **Nuevo tren (SD40)** | Sin cambios si existe paquete JSON | Sesión F6+F7 en cabina freight |

**Criterio para borrar F9 del probe:** sesión explorer completa en 323 documentada (`20260830T213100Z`
suficiente); repetir solo si cambia build o UE4SS.

---

## Orden de implementación (L0)

Tarjeta **L0** — paralela a pasos 1–6 de [PLAN_V2 § Orden](PLAN_V2.md#orden-de-implementación); no
bloquea `agent/`.

| # | Entrega | Validación mínima |
| --- | --- | --- |
| L0.1 | Esqueleto mod + `session.json` | F5 en cabina → `data/lab_exports/exports/` | ✅ |
| L0.2 | Modo `hud_batch` + `http_guess` | 16/16 HUD sin errores | ✅ `20260830T145544Z` build `f` |
| L0.3 | Modo `controls` (G-B) | F6 → levers + `layout_hint` | ✅ in-game 323 (7 palancas) |
| L0.4 | Modo `driver_aid` (C1/C2/lim2) | F7 exporta escalares (gradiente, límites, dist. señal) | ✅ exploración 323 |
| L0.4b | Catálogo señales Lua (todos los aspectos, no solo rojo) | Varias F7: verde → ámbar → rojo; comparar campos | ⬜ ver protocolo abajo |
| L0.5 | `scripts/tools/api_correlator.py` | ≥80 % HUD exact (live HTTP o mock en pytest) | ✅ script + tests |
| L0.6 | Modo `formation` (física §2) | Shift+F5 + `http_probe` / `lua_probe`; HTTP vía `--formation` | ✅ híbrido HTTP — ver § L0.6 |
| L0.6b | `reflect_shallow` seguro (Shift+F6) | Build `k`+ sin crash; árbol Simulation | ✅ `20260830T211527Z` |
| L0.6c | `graph_probe` en `formation` | Shift+F5 build `l` — `SimulationGraphInstance` / `GetSimulation` | ✅ `20260830T213100Z` |
| L0.7 | `vehicles_json_from_lab.py` → `data/vehicles/` | Desde `controls` sesión 323 | ⬜ |
| L0.8 | Tests pytest + fixtures + compare probe | Copiar `20260830T213100Z` → fixtures | ⬜ |

### Sesión referencia Class 323 — **`20260830T213100Z`** (build `20260830l`)

Barrido L0 **completo** con **HTTP en vivo** (`-HTTPAPI`): cierra L0.6 híbrido y L0.6c `graph_probe`.

| Modo | Archivo | Resultado |
| --- | --- | --- |
| `hud_batch` | `hud_batch.json` | **16/16** · parado (~0 m/s) · manómetro ~**4.28 bar** (B1) |
| `controls` | `controls.json` | `combined` · PBH muesca **1** (`-0.6`) · 7 levers |
| `driver_aid` | `driver_aid.json` | `signalAspectClass: 0` · señal ~51 m · `next_signals[]` vacío Lua |
| `formation` | `formation.json` | `partial` · `lua_probe` + `graph_probe` · `simulation{}` vacío |
| `formation_http` | `formation_http.json` | **156/156 probes OK** · cilindro **4.28 bar** · masa **45 550** |
| `reflect_shallow` | `reflect_shallow.json` | `SimulationComponent` válido · hijos skipped |
| `correlate_tick` | `correlate_tick.json` | Marca L0.5 |

`vehicle_class`: `RVM_BCC_WRM_Class323_DMS_A_C` · Cross-City.

**Usar esta carpeta para:** correlator `--formation`, fixtures L0.8, L0.7 `controls.json`, documentar L0.6.

### Sesión complementaria — **`20260830T211527Z`** (build `20260830k`)

Misma estructura L0 sin juego HTTP al correlar (útil para reflect estable y comparar builds `k` vs `l`).

| Modo | Archivo | Resultado |
| --- | --- | --- |
| `hud_batch` | `hud_batch.json` | **16/16** · parado · manómetro ~3.5 bar (B2) |
| `formation` | `formation.json` | `partial` · sin `graph_probe` (build `k`) |
| `reflect_shallow` | `reflect_shallow.json` | Primera sesión reflect seguro post-crash build `j` |

**Usar para:** comparar builds, validar reflect sin depender de HTTP live.

### Sesión histórica (`20260830T145544Z`, build `f`)

Primera sesión con F5–F7+Shift todos OK; útil como **línea base HUD en marcha** (~22 m/s, PBH muesca 6).
`formation` vacío (sin `lua_probe`); sin `reflect` útil. Mantener para L0.2/L0.4b verde y tests pytest mock.

| Modo | Archivo | Resultado |
| --- | --- | --- |
| `hud_batch` | `hud_batch.json` | **16/16** `HUD_Get*` · `errors: {}` · ~22 m/s power 2 |
| `controls` | `controls.json` | `layout_hint: combined` · PBH muesca 6 · 7 levers (sin `FindAllOf`) |
| `driver_aid` | `driver_aid.json` | **Línea base verde:** `signalAspectClass: 0`, `distanceToSignal` ~411 m,
  `signalSeen: true` · `next_signals[]` vacío en Lua (HTTP sí lista Clear/Approach/Stop) |
| `formation` | `formation.json` | Vacío en build `f` (sin diagnóstico híbrido) |
| `correlate_tick` | `correlate_tick.json` | Marca para L0.5 correlator |

`vehicle_class`: `RVM_BCC_WRM_Class323_DMS_A_C` · Cross-City · build `20260830f`.

**Hallazgos para otros trenes:** F6 lista lo que **existe** en el actor (`IrregularLeverComponent`,
`PushButtonComponent`, …) aunque el autopilot no lo use. F5 lista qué `HUD_Get*` responde (diesel
tendrá RPM ≠ 0; freight otro brake handle). Comparar sesiones por `vehicle_class`, no asumir nombres
del 323.

### Cierre Class 323 → siguiente tren

**323 (explorer):** con la sesión **`20260830T213100Z`** el barrido por teclas L0 está **cerrado** (F5–F7 + Shift).
L0.6 física = **canal HTTP**; Lua tick = HUD + mandos. Queda trabajo de **producto**, no de cabina:

| Pendiente | Tipo | ¿Bloquea otro tren? |
| --- | --- | --- |
| L0.7 `class_323.json` desde `controls.json` | script Python | No |
| L0.4b enum `signalAspectClass` + arrays TArray | código / sesión con rojo | No — C1 en probe es aparte |
| L0.5 correlator live | normalizar rutas `DriverAid.Data.*`; correlar justo tras F5 | No — pytest mock OK |
| Mejoras correlator | `DriverAid` `/` → `.`; aviso Δt vs captura | No |

**Siguiente tren (cuando toque):** misma rutina — una sesión `exports/<timestamp>/` con F5–F7 (+ Shift
si interesa), `notas_sesion.md`, `vehicle_class` distinto. Comparar con 323; no reutilizar nombres de
palanca ni asumir `combined`. Freight / diesel: priorizar F6 (layout split) y F5 (RPM, brakes).

No hace falta “terminar al 100 %” el 323 en L0.4b/L0.6 antes de explorar otro vehículo; sí conviene
cerrar **L0.7** para el 323 si el autopilot sigue en Class 323.

### L0.6 — qué captura `formation` (Shift+F5)

| Bloque JSON | Origen Lua | Uso |
| --- | --- | --- |
| `simulation.BrakeCylinder_*` | `actor.Simulation` | `Pressure_BAR` — probe `brake_cyl_bar` |
| `simulation.ClampPowerInput.Mass` | Simulation | Masa (futuro `massFactor`) |
| `simulation.Axle_*` | Simulation | Odo, adherencia, slip |
| `summary.brake_cyl_bar` / `odo_m` | derivados | Cruce con GetData |
| `http_guess` | doble ruta | Solo si Lua leyó valor numérico |
| `http_probe[]` | siempre (build `i`+) | Rutas HTTP a validar con Python |
| `lua.lua_probe{}` | siempre (build `i`+) | `index_ok`, `child_valid`, `fields` por nodo |

**Sesión referencia híbrida:** `20260830T213100Z` (build `20260830l`). Histórico: `211527Z` (`k`), `192858Z` (`i`).

| Hallazgo | Valor |
| --- | --- |
| `pairs(sim)` | 0 claves — hijos no iterables |
| `sim["BrakeCylinder_2_1"]` | `index_ok: true`, `child_type: userdata` |
| `IsValid` en hijos | **false** en los 9 nodos probados (también vía `graph_probe`) |
| `fields` en Lua | `{}` — propiedades no legibles con accessors actuales |
| `simulation{}` en export | vacío — el mod no marca OK hasta leer un campo |
| `reflect` en `Simulation` | Componente **válido**; props `SimulationGraph`, `SimulationGraphInstance` |
| **HTTP `--formation`** | **156/156 OK** · `BrakeCylinder_2_1.Pressure_BAR` = **4.28 bar** · `ClampPowerInput.Mass` = **45 550** |
| **Ruta canónica cilindro** | `CurrentFormation/0/Simulation/BrakeCylinder_2_1.Pressure_BAR` |

**Conclusión cerrada (323):** presión cilindro, masa y odo vía **HTTPAPI**; probe en tick debe usar HTTP
(o proxy HUD) para `brake_cyl_bar`, no `actor.Simulation` en Lua. Correlator:

```bat
python scripts/tools/api_correlator.py data/lab_exports/exports/20260830T213100Z --formation
python scripts/tools/api_correlator.py data/lab_exports/exports/20260830T213100Z
```

Escribe `formation_http.json` + `formation_report.md` (L0.6) y `correlation_report.md` (L0.5).
**Nota L0.5 live:** si el correlator corre minutos después de F5, HUD/DriverAid pueden divergir por
desfase temporal; `correlation_report.md` de `213100Z` muestra ~50 % HUD exact por ese motivo.

### SimulationGraph — qué es (y por qué importa)

En TSW la física del tren no es “un montón de propiedades sueltas” en el actor: es un **grafo de
simulación** (tuberías de aire, cilindros, ejes, compresor, etc.) colgado del componente
`Simulation` del vehículo.

```text
actor (Class 323)
 └── Simulation  (SimulationComponent)     ← válido en UE4SS; Shift+F6 lo refleja
      ├── SimulationGraph                  ← plantilla / definición del grafo (asset)
      ├── SimulationGraphInstance          ← instancia en ejecución con estado actual
      └── [nodos por nombre]               ← BrakeCylinder_2_1, Axle_1_1, …
           └── Pressure_BAR, Mass, …       ← lo que HTTP lee en /Simulation/...
```

| Pieza | Rol aproximado | Lo que vimos en `213100Z` |
| --- | --- | --- |
| **`SimulationComponent`** | Contenedor UE en el actor | `IsValid: true` · funciones `GetSimulation`, `ResetSimulation` |
| **`SimulationGraph`** | Definición del grafo (wiring, tipos de nodo) | Propiedad reflejada; valor = `userdata` (no escalar) |
| **`SimulationGraphInstance`** | Grafo **vivo** con presiones/masas actuales | Idem — candidato a leer en Lua sin tocar hijos inválidos |
| **`sim["BrakeCylinder_2_1"]`** | Acceso por nombre al nodo | `index_ok` pero `IsValid: false` → **no** introspectar con UE4SS |
| **HTTP `.../Simulation/BrakeCylinder_2_1.Pressure_BAR`** | Mismo grafo, API del juego | Funciona; es el canal fiable hoy para L0.6 |

**Por qué `formation.lua` falla y HTTP no:** HTTP recorre el grafo por rutas de texto; UE4SS expone
el componente y handles a nodos, pero los nodos hijos no son `UObject` válidos para `ForEachProperty`.
Los campos de presión viven **dentro** del `SimulationGraphInstance`, no como `sim.Pressure_BAR` en la
raíz (el `field_probe` del componente devuelve `userdata` en esos nombres, no números).

**L0.6c cerrado (build `20260830l`):** `graph_probe` confirma que `SimulationGraphInstance`,
`SimulationGraph` y `GetSimulation()` son **válidos** (`SimulationRuntime` / `SimulationAsset`), pero
los nodos hijo siguen `index_ok` + `child_valid: false` + `fields: {}` en los tres parents. **No** más
experimentos Lua en hijos Simulation — riesgo crash; canal fiable = HTTP.

### Seguridad `reflect_shallow` — árbol Simulation (Shift+F6)

Build `20260830j` amplió Shift+F6 para reflejar `actor.Simulation` y hijos conocidos. En Class 323
los hijos existen (`index_ok`) pero **`IsValid() == false`**. Llamar `GetClass` / `ForEachProperty` /
`ForEachFunction` / `GetFullName` sobre esos userdata provoca **crash nativo** (`EXCEPTION_ACCESS_VIOLATION`
en UE4SS, no capturable con `pcall` Lua).

| Evento | Sesión / build |
| --- | --- |
| Crash TSW | `20260830T205643Z` — último log: `formation` OK; **sin** línea `reflect_shallow` |
| Dump | `%LOCALAPPDATA%/../Documents/My Games/TrainSimWorld6/Saved/Crashes/UE4CC-...` |
| Fix | Build **`20260830k`**: introspección solo si `IsValid`; hijos inválidos → stub `introspection: skipped` |

**Regla para código futuro:** comprobar `obj:IsValid()` antes de cualquier reflect UE4SS. `lua_probe`
en `formation.json` indica si un nodo es candidato seguro (`child_valid: true`) o solo stub.

Sesión `145544Z` con build `f` salió vacía en `simulation{}` por otra vía (sin `lua_probe`). Builds
`g`–`i` usan `sim[name]` sin exigir `IsValid` en hijo; los campos siguen sin leerse en 323.

### Protocolo L0.4b — catálogo de señales (antes de C1 en probe)

**Idea:** no ir a cazar solo el rojo. Primero documentar **cualquier** semáforo adelante en Lua; después
comparar si el mismo campo (`signalAspectClass`, `distanceToSignal`, …) cambia de valor cuando el
aspecto pasa de verde a rojo, o si el juego usa **otro** nombre para el rojo.

| Fase | Qué hacer | Qué anotar |
| --- | --- | --- |
| 1. **Línea base** | F7 con señal **verde/clear** adelante (sesión `145544Z`) | `signalAspectClass`, `distanceToSignal`, `next_signals[]` |
| 2. **Cola adelante** | F7 en marcha con varias señales visibles en ruta | ¿`next_signals[]` se llena en Lua o solo en HTTP? |
| 3. **Otro aspecto** | F7 con **ámbar / double yellow** si aparece | ¿mismo campo, otro número enum? |
| 4. **Rojo** | F7 frenando ante **Stop** | ¿cambia `signalAspectClass` de 0→? · ¿o solo `next_signals[2]`? |
| 5. **Conclusión** | Tabla campo × aspecto | Qué escalar meter en GetData para C1 (`signal_red` es **filtro**, no objetivo del explorer) |

**Sesión referencia (verde):** `signalAspectClass: 0` con señal vista — candidato a **Clear** (HTTP
RailBridge en la misma ruta usa `"Clear"`). Falta confirmar con captura en rojo si `0→N` o si hay
string en otro sitio.

**Autopilot (más adelante):** solo necesita `signal_red=1` + distancia; el explorer guarda el catálogo
completo para no adivinar en código.

---

### Desbloqueos respecto a PLAN_V2

| Paso PLAN_V2 | Explorer previo |
| --- | --- |
| 1 cerrado (C1 en probe) | L0.4 ✅ escalares; L0.4b enum/TArray si cableamos C1 |
| 6 paquete JSON G-B | L0.3 ✅ sesión referencia → L0.7 |
| Depuración probe | L0.1–L0.2 ✅ — candidato quitar F9 en probe |

---

## Qué NO hacer

- Escribir en `%TEMP%\TSW6Bridge\`
- Registrar el mismo `ReceiveTick` que el probe (doble hook / hitch)
- Añadir campos a GetData desde el explorer (solo propuesta en doc + JSON)
- Unificar mods en un solo `main.lua`
- Crawler HTTP dentro de Lua (lento; usar Python con `-HTTPAPI`)
- Introspección UE4SS (`GetClass`, `ForEachProperty`, `GetFullName`) sobre UObject con `IsValid == false`
  (crash nativo; ver § reflect Simulation)

---

## Criterios de éxito

| # | Criterio |
| --- | --- |
| 1 | Probe puede desactivar F9 sin perder capacidad de investigación |
| 2 | `class_323.json` generable desde exports sin editar probe |
| 3 | C1: nombres de señal documentados antes de `extract_signal_red` en probe |
| 4 | Modo `controls` validado en 323 antes del paso 6 del plan |
| 5 | Tamaño total explorer <1500 líneas; ningún archivo >300 |
| 6 | Cada tren nuevo: al menos una carpeta `exports/<session>/` archivada (exploración, no prod) |

---

## Bitácora

| Fecha | Nota |
| --- | --- |
| 2026-08-30 | Plan inicial — separación laboratorio vs probe producción |
| 2026-08-30 | L0.1 esqueleto + L0.2 `hud_batch` · `install_ue4ss_explorer.bat` |
| 2026-08-30 | L0.3 `controls` + `compare_lab_controls.py` |
| 2026-08-30 | Teclas F5–F7 (conflicto F10 consola); exports en `data/lab_exports/` |
| 2026-08-30 | F6: `USE_FINDALL_CONTROLS=false` (freeze); `LAB_CAPTURA_F5.md` |
| 2026-08-30 | Estrategia Lua-first vs HTTP lento; dumps Desktop como catálogo |
| 2026-08-30 | L0.4 `driver_aid.lua` — build `20260830f` |
| 2026-08-30 | **Sesión `20260830T145544Z`** — F5–F7+Shift todos los modos; 323 HUD 16/16; F6 OK |
| 2026-08-30 | L0.5 `api_correlator.py` + `tests/test_api_correlator.py` |
| 2026-08-30 | L0.6 `formation.lua` ampliado — build `20260830g` |
| 2026-08-30 | L0.6 híbrido — `http_probe` + `lua_probe` (build `i`); sesión `20260830T192858Z` |
| 2026-08-30 | `api_correlator.py --formation` → `formation_http.json` |
| 2026-08-30 | **Crash** Shift+F6 build `j` — reflect en hijos Simulation inválidos; fix build `20260830k` |
| 2026-08-30 | **Sesión ref. `20260830T211527Z`** — L0 completo; § SimulationGraph; reflect seguro |
| 2026-08-30 | L0.6c `formation.lua` — `graph_probe` SimulationGraphInstance / GetSimulation (build `l`) |
| 2026-08-30 | **Sesión ref. `20260830T213100Z`** — L0.6 HTTP **cerrado** (156/156); L0.6c sin escalares Lua |

---

## Referencias

| Archivo | Relación |
| --- | --- |
| [LAB_CAPTURA_F5.md](LAB_CAPTURA_F5.md) | Qué recopila F5, protocolo frenar/acelerar |
| `data/lab_exports/exports/20260830T213100Z/` | **Sesión referencia 323** (L0 completo + HTTP, build `l`) |
| `data/lab_exports/exports/20260830T211527Z/` | Complementaria reflect estable (build `k`) |
| `data/lab_exports/exports/20260830T145544Z/` | Histórica HUD en marcha + pytest mock |
| [PLAN_V2.md](PLAN_V2.md) | Producto v2, probe §4.1, G-B §1, C1 §3 |
| [CANAL_CONTROL.md](../CANAL_CONTROL.md) | Contrato GetData (D2) — destino de campos aprobados |
| `Desktop\investigacion tsw 6\apis\` | Exports RailBridge HTTP (referencia, no en repo) |
| [CURRENTFORMATION_API.md](../reference/CURRENTFORMATION_API.md) | Catálogo HTTP física / HUD |
| [DRIVERAID_API.md](../reference/DRIVERAID_API.md) | Vía, señales, planning |
| [DRIVERINPUT_API.md](../reference/DRIVERINPUT_API.md) | Escritura mandos / nombres lever |
| `mods/TelemetryProbeMod/Scripts/main.lua` | Probe actual (no mezclar) |
| `mods/ApiExplorerMod/Scripts/` | Mod laboratorio (este plan) |
| `scripts/tools/api_correlator.py` | L0.5 HTTP ↔ `http_guess` |
| `scripts/ue4ss/install_ue4ss_explorer.bat` | Instalador UE4SS |

### Correlator (L0.5)

```bat
python scripts/tools/api_correlator.py data/lab_exports/exports/20260830T213100Z
python scripts/tools/api_correlator.py data/lab_exports/exports/20260830T213100Z --hud-only --min-exact 0.8
python scripts/tools/api_correlator.py data/lab_exports/exports/20260830T213100Z --formation
python scripts/tools/api_correlator.py data/lab_exports/exports/20260830T145544Z --dry-list
```

Con TSW6 en marcha y `-HTTPAPI`: escribe `correlation_report.md` en la carpeta de sesión.
`--formation` escribe además `formation_http.json` y `formation_report.md` (L0.6 híbrido).
