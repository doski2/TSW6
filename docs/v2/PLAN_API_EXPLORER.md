# Plan ApiExplorerMod — laboratorio Lua (HTTP ↔ UE)

**Fecha:** 2026-08-30 (actualizado 2026-09-01)

## Estado:** L0 **cerrado en 323** · build explorer **`20260901a`

**Sesión referencia:** [`20260830T213100Z`](../../data/lab_exports/exports/20260830T213100Z/)
(Cross-City) ·
tracción [`210515Z`](../../data/lab_exports/exports/20260901T210515Z/) · amperímetro
[`211818Z`](../../data/lab_exports/exports/20260901T211818Z/)
**Plan maestro:** [PLAN_V2.md](PLAN_V2.md) · **Probe producción:**
[PENDIENTE_DYNAMICHUD.md](../v1/PENDIENTE_DYNAMICHUD.md)
**Captura:** [LAB_CAPTURA_F5.md](LAB_CAPTURA_F5.md) · [LAB_CAPTURA_AMPS.md](LAB_CAPTURA_AMPS.md)
**Referencias API:** [TSW_HTTPAPI_INDEX.md](../reference/TSW_HTTPAPI_INDEX.md) ·
[CURRENTFORMATION_API.md](../reference/CURRENTFORMATION_API.md) ·
[DRIVERAID_API.md](../reference/DRIVERAID_API.md) ·
[DRIVERINPUT_API.md](../reference/DRIVERINPUT_API.md)
**Dumps HTTP (RailBridge):** `Desktop\investigacion tsw 6\apis\` — válidos; mismos nombres que
Lua/HTTPAPI

### Índice

- [Resumen](#resumen) · [Estado 323 (ejecutivo)](#estado-323--resumen-ejecutivo)
- [Alineación PLAN_V2](#alineación-con-plan_v2) · [Lua vs

  HTTP](#estrategia-lua-vs-http-decisión-2026-08-30)

- [Arquitectura](#arquitectura) · [Modos F5–F7](#modos-de-captura-teclas-propuestas)
- [L0 checklist](#orden-de-implementación-l0) · [Sesiones 323

  (tabla)](#sesiones-lab-323--tabla-única)

- [Siguiente tren](#cierre-class-323--siguiente-tren) · [L0.6

  física](#l06--qué-captura-formation-shiftf5) (6d/6e/6f)

- [Cableado → probe](#mapa-cableado--lab--archivo-destino-documentación-sin-cablear-aún) ·

  [Bitácora](#bitácora)

---

## Estado 323 — resumen ejecutivo

| Señal / tema | ¿Probe 20 Hz? | Notas |
| --- | --- | --- |
| HUD 16× (`speed`, brakes, `dyn_brake`, …) | ✅ ya en GetData | Sesión `213100Z` |
| C1 `signalAspectClass` 0/1/2 + distancia | ⬜ cablear probe | Lab cerrado L0.4b |
| `is_slipping` HUD | ⬜ 9b-a log | Evidencia `214213Z` |
| `brake_cyl_bar` | ✅ probe `HUD_GetBrakeGauge_1` | Simulation Lua bloqueado; HTTP solo lab |
| Masa HTTP / `mass_factor` | ❌ F-B off | No correlación vagones |
| `HUD_GetTractiveEffort` / `HUD_GetAmmeter` | ❌ catálogo 323 | Siempre 0; otro tren puede variar |
| `NetTractiveEffort` Simulation | ❌ catálogo HTTP | +651 N en `210515Z`; Lua bloqueado |
| G-B `class_323.json` | ✅ L0.7 | Paso 6 IPC pendiente producto |

**¿Va al probe?** F5/F7 devuelve valor ≠ 0 en **este** `vehicle_class` → candidato D2. Siempre 0 en
323 → catálogo (no asumir en otro tren). Ver [checklist siguiente
tren](#cierre-class-323--siguiente-tren).

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
existe para **descubrir** eso en una sesión de cabina y dejar constancia en JSON — no para meter
cada
campo en GetData.

| Destino del dato | Quién decide | Ejemplo 323 |
| --- | --- | --- |
| **Producción** (~20 Hz) | Revisión humana + D2 → probe | `speed_ms`, `gradient_pct`, `PowerBrakeHandle` |
| **Paquete G-B** | L0.7 desde `controls.json` | `layout_hint: combined`, mapa muescas PBH |
| **Catálogo / referencia** | Se guarda en export; no se cablea | gauges, `RegenBrakes` |
| **Candidato probe (lab)** | Revisión por `vehicle_class` | diesel: RPM; EMU distinta: repetir L0.6f |
| **Catálogo 323 (no probe)** | Cerrado en lab — otro tren puede variar | `HUD_GetAmmeter`, `HUD_GetTractiveEffort`, `NetTractiveEffort` HTTP |
| **Otro tren** | Nueva sesión F5–F7 en esa cabina | SD40: palancas split, sin PBH UK |

**323 y lab:** barrido L0 **cerrado** (build `20260901a`). No hace falta más capturas 323 salvo
regresión del mod. El valor del mod **crece con cada tren nuevo**.

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
| D1 producto `V2/tsw6v2/` | Correlator Python = herramienta aparte, no en `V2/tsw6v2/` |
| F9 / `pairs` en probe | Migrar aquí; probe pierde ~300–500 líneas cuando se valide |

**Regla de oro:**

```text
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
```

### Árbol del mod (objetivo ~800–1200 líneas total)

```text
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
```

### Ejemplo `hud_batch.json`

```json
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

**No hay menú en pantalla** — las capturas son con **F5–F7 en cabina** (escenario cargado, dentro
del
tren). Comprobar carga en `UE4SS.log`: línea `[ApiExplorer] Mod loaded`.

Instalación: `install_ue4ss_explorer.bat` en la raíz del repo (no copiar solo el `.bat` sin
`mods/`).

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

**No** hay log continuo ~20 Hz (eso es del probe en `GetData.txt`). El explorer solo escribe al
pulsar
tecla. Para sesión de laboratorio: guardar UE4SS.log tras F5–F7 o copiar la carpeta `exports\`.
Ver protocolo multi-captura en [LAB_CAPTURA_F5.md](LAB_CAPTURA_F5.md).

---

## Tests

Separados del probe (D7 / `parse_probe_line`). El explorer valida **exports JSON**, no el juego en
CI.

| Nivel | Qué | Cuándo | Estado |
| --- | --- | --- | --- |
| **In-game** | L0.2: `hud_batch.json` 16/16 sin `errors[]` | 323 sesión referencia | ✅ `20260830T145544Z` |
| **In-game** | L0.3: `controls.json` con levers + `layout_hint` | 323 F6 sin freeze | ✅ misma sesión |
| **In-game** | L0.4: `driver_aid.json` escalares | 323 F7; arrays TArray pendientes | 🟡 parcial |
| **In-game** | L0.4b: enum `signalAspectClass` 0/1/2 + distancia Lua | UK 323 verde/ámbar/rojo | ✅ `212529Z`/`214213Z` |
| **Fixture pytest** | `tests/fixtures/lab/hud_batch_323.json` + parser | Sesión `213100Z` en repo | ✅ L0.8 |
| **Unit** | `tests/test_lab_serialize.py` — round-trip JSON Lua-like | Sin juego | ✅ L0.8 |
| **Compare script** | `compare_lab_controls.py` — `layout_hint` vs `detect_control_layout` | JSON en disco | ✅ L0.3 |
| **Correlator** | `api_correlator.py` — HTTP vs `http_guess` | `-HTTPAPI` + export en disco | ✅ pytest mock; live con juego |
| **Compare script** | `compare_lab_vs_probe.py` — `hud_batch` vs línea GetData | Dos archivos en disco | ✅ L0.8 |

**Regla:** los tests del autopilot (`test_ue4ss_reader`, etc.) **no** dependen del explorer. Si el
probe está OFF, no hay GetData — el compare in-game solo tiene sentido con **ambos mods** en la
misma
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

- Teclas distintas con probe ON: probe F7/F8/F9 · explorer F5–F7 (+ Shift). **Sesión lab:** probe

  OFF.

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

**Criterio para borrar F9 del probe:** sesión explorer completa en 323 documentada
(`20260830T213100Z`
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
| L0.4b | Catálogo señales Lua (`signalAspectClass` enum) | F7 verde → ámbar → rojo (323 UK) | ✅ enum cerrado — ver § L0.4b |
| L0.5 | `scripts/tools/api_correlator.py` | ≥80 % HUD exact (live HTTP o mock en pytest) | ✅ script + tests |
| L0.6 | Modo `formation` (física §2) | Shift+F5 + `http_probe` / `lua_probe`; HTTP vía `--formation` | ✅ híbrido HTTP — ver § L0.6 |
| L0.6b | `reflect_shallow` seguro (Shift+F6) | Build `k`+ sin crash; árbol Simulation | ✅ `20260830T211527Z` |
| L0.6c | `graph_probe` en `formation` | Shift+F5 build `l` — `SimulationGraphInstance` / `GetSimulation` | ✅ `20260830T213100Z` |
| L0.6d | `traction_probe` en `formation` | Shift+F5 — `Axle/Axle.NetTractiveEffort` HTTP validado; Lua bloqueado | ✅ HTTP `20260901T210515Z` |
| L0.6e | RPM motor (`HUD_GetEngineRPM`) | 323 EMU: siempre 0; diesel: repetir F5 | ✅ 323 catálogo · 🔄 otro tren |
| L0.6f | Amperímetro (`HUD_GetAmmeter`) | 323: **catálogo** (`211818Z` Amps=0 con P2 @ 49 mph) | ✅ 323 · 🔄 repetir en otro tren |
| L0.7 | `vehicles_json_from_lab.py` → `data/vehicles/` | Desde `controls` sesión 323 | ✅ `class_323.json` desde `213100Z` |
| L0.8 | Tests pytest + fixtures + compare probe | `tests/fixtures/lab/20260830T213100Z/` | ✅ |

### Sesiones lab 323 — tabla única

| Sesión | Escenario | Aporta principal |
| --- | --- | --- |
| [`213100Z`](../../data/lab_exports/exports/20260830T213100Z/) | Cross-City ref · build `l` | L0 completo + HTTP 156/156 · G-B · fixtures |
| [`145544Z`](../../data/lab_exports/exports/20260830T145544Z/) | HUD en marcha ~22 m/s | L0.2 baseline · pytest mock |
| [`211527Z`](../../data/lab_exports/exports/20260830T211527Z/) | reflect post-crash `k` | Shift+F6 seguro |
| [`212529Z`](../../data/lab_exports/exports/20260831T212529Z/) | Nieve · ámbar | L0.4b enum **1** |
| [`214213Z`](../../data/lab_exports/exports/20260831T214213Z/) | Nieve · rojo + slip | enum **2** · `IsSlipping` HUD · masa 44 430 kg |
| [`210515Z`](../../data/lab_exports/exports/20260901T210515Z/) | Tracción P aplicada | L0.6d HTTP **+651 N** · build `20260901a` |
| [`211818Z`](../../data/lab_exports/exports/20260901T211818Z/) | P2 @ ~49 mph | L0.6f **Amps=0** · barrido L0 completo |

Detalle por sesión en subsecciones siguientes (opcional si ya conoces la tabla).

### Sesión referencia Class 323 — **`20260830T213100Z`** (build `20260830l`)

Barrido L0 **completo** con **HTTP en vivo** (`-HTTPAPI`): cierra L0.6 híbrido y L0.6c
`graph_probe`.

| Modo | Archivo | Resultado |
| --- | --- | --- |
| `hud_batch` | `hud_batch.json` | **16/16** · parado (~0 m/s) · manómetro ~**4.28 bar** (B1) |
| `controls` | `controls.json` | `combined` · PBH muesca **1** (`-0.6`) · 7 levers |
| `driver_aid` | `driver_aid.json` | `signalAspectClass: 0` · señal ~51 m · `next_signals[]` vacío Lua |
| `formation` | `formation.json` | `partial` · `lua_probe` + `graph_probe` · `simulation{}` vacío |
| `formation_http` | `formation_http.json` | **156/156 probes OK** · cilindro **4.28 bar** · masa **45 550** kg (**3 coches**) |
| `reflect_shallow` | `reflect_shallow.json` | `SimulationComponent` válido · hijos skipped |
| `correlate_tick` | `correlate_tick.json` | Marca L0.5 |

`vehicle_class`: `RVM_BCC_WRM_Class323_DMS_A_C` · Cross-City.

**Usar esta carpeta para:** correlator `--formation`, fixtures L0.8, L0.7 `controls.json`,
documentar L0.6.

### Sesión nieve / adherencia — **`20260831T212529Z`** y **`20260831T214213Z`** (build `20260830l`)

Mismo tren (`Class323`), escenario con **nieve** y composición distinta a Cross-City. Cierra

##### L0.4b

(enum señales) y primera evidencia **slip en marcha** (F5).

| Sesión | F7 `signalAspectClass` | `distanceToSignal` | F5 slip (HUD) | HTTP `ClampPowerInput.Mass` |
| --- | --- | --- | --- | --- |
| `212529Z` | **1** (ámbar / caution) | ~58 m | `false` (parado) | — (sin `--formation`) |
| `214213Z` | **2** (**Stop / rojo** — confirmado in-game) | ~552 m* | **`true`** + `TractionLocked` @ ~24 m/s | **44 430** kg · **6 coches** (conteo manual) |

\*Distancia DriverAid a la señal indexada; puede ser grande aunque el aspecto sea rojo. Para C1
conviene
F7 adicional **cerca** del Stop (<80 m) si hace falta afinar `signal_dist_cm`.

| Modo | Hallazgo clave |
| --- | --- |
| `driver_aid` | `signalAspectClass` y `distanceToSignal` legibles en **Lua** (`lua.scalars`); `next_signals[]` sigue vacío |
| `hud_batch` | `HUD_GetIsSlipping` / `HUD_GetIsTractionLocked` — primera captura **en marcha** con slip `true` (`214213Z`) |
| `formation_http` | `CurrentTrackAdhesion` ~**0,01** (nieve) vs ~**0,99** Cross-City; masa total vía `ClampPowerInput.Mass` |

**Masa vs vagones (conteo manual 2026-09-01):** Cross-City **3 coches** → HTTP **45 550** kg;
nieve **6 coches** → HTTP **44 430** kg. **Más coches, menos masa** — no hay correlación lineal.
**Decisión:** no usar `mass_factor` en frenado (paso 9); mantener F-A = 1,0. La ruta HTTP queda como
telemetría/log opcional, no como entrada de `physics.py` hasta entender qué mide
`ClampPowerInput.Mass`.

### Sesión complementaria — **`20260830T211527Z`** (build `20260830k`)

Misma estructura L0 sin juego HTTP al correlar (útil para reflect estable y comparar builds `k` vs
`l`).

| Modo | Archivo | Resultado |
| --- | --- | --- |
| `hud_batch` | `hud_batch.json` | **16/16** · parado · manómetro ~3.5 bar (B2) |
| `formation` | `formation.json` | `partial` · sin `graph_probe` (build `k`) |
| `reflect_shallow` | `reflect_shallow.json` | Primera sesión reflect seguro post-crash build `j` |

**Usar para:** comparar builds, validar reflect sin depender de HTTP live.

### Sesión histórica (`20260830T145544Z`, build `f`)

Primera sesión con F5–F7+Shift todos OK; útil como **línea base HUD en marcha** (~22 m/s, PBH muesca
6).
`formation` vacío (sin `lua_probe`); sin `reflect` útil. Mantener para L0.2/L0.4b verde y tests
pytest mock.

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

##### 323 (explorer):** barrido L0 **cerrado** en cabina. Queda trabajo de **producto

(probe/autopilot), no de lab:

| Pendiente producto | Tipo | ¿Bloquea otro tren? |
| --- | --- | --- |
| C1 `signal_red` + `signal_dist_cm` en probe | cablear `main.lua` | No |
| 9b-a `is_slipping` en GetData | log | No |
| Paso 6 IPC + `class_323.json` | G-B ya generado L0.7 ✅ | No |
| Quitar F9 del probe | depuración | No |
| Mejoras correlator (Δt, rutas DriverAid) | tooling | No |

**Siguiente tren (cuando toque):** **no asumir** resultados del 323. Una sesión nueva
`exports/<timestamp>/` con barrido F5–F7 (+ Shift) y pruebas **por vehículo**:

| Prueba | Modo | Doc | 323 | Otro tren |
| --- | --- | --- | --- | --- |
| HUD 16× | F5 | [LAB_CAPTURA_F5.md](LAB_CAPTURA_F5.md) | ✅ | Repetir |
| Amperímetro / regen | F5 ×5 | [LAB_CAPTURA_AMPS.md](LAB_CAPTURA_AMPS.md) | **Amps siempre 0** | Puede ≠ 0 (EMU/diesel) |
| Esfuerzo tractivo HUD | F5 | L0.6d | **siempre 0** | Comprobar |
| Simulation tracción | Shift+F5 + `--formation` | L0.6d | HTTP sí, Lua no | Repetir |
| RPM motor | F5 | L0.6e | 0 (EMU) | Diesel: esperar ≠ 0 |
| Layout mandos | F6 | L0.3 | `combined` | split freight, etc. |
| Señales / C1 | F7 | L0.4b | enum UK | Por país/vehículo |

`vehicle_class` en `session.json` + `notas_sesion.md`. Analizar amperímetro:
`summarize_hud_amps.py <session>`. Freight / diesel: priorizar F6 (layout split), F5 (RPM, brakes),
protocolo amperímetro/RPM completo aunque el 323 no haya mostrado esas señales.

No hace falta repetir el 323 en lab salvo regresión de mod; **sí** repetir checklist completo en
cada **nuevo** `vehicle_class`.

### L0.6 — qué captura `formation` (Shift+F5)

| Bloque JSON | Origen Lua | Uso |
| --- | --- | --- |
| `simulation.BrakeCylinder_*` | `actor.Simulation` (explorer) | HTTP `--formation`; probe `brake_cyl_bar` por otro camino Lua |
| `simulation.ClampPowerInput.Mass` | Simulation | Masa — catálogo HTTP (F-B off) |
| `simulation.Axle_*` | Simulation | Odo, adherencia, slip |
| `summary.brake_cyl_bar` / `odo_m` | derivados | Cruce con GetData |
| `http_guess` | doble ruta | Solo si Lua leyó valor numérico |
| `http_probe[]` | siempre (build `i`+) | Rutas HTTP a validar con Python |
| `lua.lua_probe{}` | siempre (build `i`+) | `index_ok`, `child_valid`, `fields` por nodo |
| `lua.traction_probe{}` | build `20260901a`+ | `Axle_1_1` / `Axle_2_1` vía `direct`, `Axle`, `Wheel` |
| `summary.tractive_effort_n` | si Lua leyó | Mejor candidato distinto de 0 (no `HUD_GetTractiveEffort`) |

**Sesión referencia híbrida:** `20260830T213100Z` (build `20260830l`). Histórico: `211527Z` (`k`),
`192858Z` (`i`).

#### Hallazgos L0.6 (323) — Simulation / HTTP

| Hallazgo | Valor |
| --- | --- |
| `pairs(sim)` | 0 claves — hijos no iterables |
| `sim["BrakeCylinder_2_1"]` | `index_ok: true`, `child_type: userdata` |
| `IsValid` en hijos | **false** en los 9 nodos probados (también vía `graph_probe`) |
| `fields` en Lua (explorer) | `{}` — explorer no lee escalares de nodos |
| `simulation{}` en export explorer | vacío — el mod no marca OK hasta leer un campo |
| `reflect` en `Simulation` | Componente **válido**; props `SimulationGraph`, `SimulationGraphInstance` |
| **HTTP `--formation`** | **156/156 OK** (`213100Z`) · cilindro **4.28 bar** · masa **45 550** |
| **Ruta canónica cilindro** | `CurrentFormation/0/Simulation/BrakeCylinder_2_1.Pressure_BAR` |

**Conclusión explorer vs probe:** el **explorer** no lee presión/masa en nodos Simulation (Lua
bloqueado). El **probe** obtiene `brake_cyl_bar` en tick vía **`HUD_GetBrakeGauge_1`**
(`RedNeedle (Pa)` ÷ 100 000 ≈ bar; coincide con HTTP cilindro en `213100Z`). HTTP
`Simulation/BrakeCylinder_*` queda para lab/correlator, no para tick. Masa/tracción HTTP = **catálogo**
solamente.

```bat
```

Escribe `formation_http.json` + `formation_report.md` (L0.6) y `correlation_report.md` (L0.5).
**Nota L0.5 live:** si el correlator corre minutos después de F5, HUD/DriverAid pueden divergir por
desfase temporal; `correlation_report.md` de `213100Z` muestra ~50 % HUD exact por ese motivo.

### L0.6d — esfuerzo tractivo (no HUD) — **cerrado HTTP / Lua bloqueado**

`HUD_GetTractiveEffort` existe en F5 pero devuelve **0 siempre** en Class 323 — **no es un fallo del
mod**:
es la API del instrumento de cabina; la 323 no alimenta esa aguja. El esfuerzo real está en

##### Simulation

(solo HTTP).

| Canal | 323 | Sesión ref. |
| --- | --- | --- |
| `HUD_GetTractiveEffort` (F5 Lua + HTTP) | **Siempre 0** | todas |
| `Simulation/Axle_1_1/Axle.NetTractiveEffort` (HTTP) | **+651 N** con potencia | `20260901T210515Z` |
| mismo (HTTP) | **-19.5 N** patinaje | `20260831T214213Z` |
| `lua.traction_probe` (Shift+F5) | `index_ok` pero `fields_by_via: {}` | `210515Z` |

**Conclusión probe:** esfuerzo tractivo = **solo catálogo HTTP**. **No cablear** en GetData.
Frenado/tracción en tick 323: `dyn_brake` + `train_brake` + `brake_cyl_bar` + `accel_ms2` (sin
`amps`
ni HUD TractiveEffort — ver L0.6f).

Ruta HTTP canónica: `CurrentFormation/0/Simulation/Axle_1_1/Axle.NetTractiveEffort` (la ruta plana
`Axle_1_1.NetTractiveEffort` suele devolver vacío).

```bat
```

**Protocolo histórico Shift+F5** (build `20260901a`): ver captura `210515Z` — 212/216 HTTP OK,
tracción confirmada, Lua no.

### L0.6e — RPM motor (`HUD_GetEngineRPM`) vs RPM rueda

**Estado Class 323 (EMU):** `HUD_GetEngineRPM` responde en F5 (`Needle1/2 RPM`) pero **siempre 0** —
no hay motor diésel. **No cablear en probe 323** ni usar para P1/frenado.

| Señal | Origen | 323 frenado hoy | Diesel / freight (futuro) |
| --- | --- | --- | --- |
| `HUD_GetEngineRPM` | F5 Lua | ❌ siempre 0 | ✅ idle / notch / ventana DB |
| `Simulation/Axle_*/Wheel.AngularVelocity_RPM` | HTTP / formation | 🟡 ≈ velocidad | slip motor↔rueda si hay RPM motor |
| `HUD_GetElectricBrakeHandle` | F5 · probe `dyn_brake` | ✅ regen UK | N/A o distinto nombre |
| `HUD_GetAmmeter` | F5 | ❌ catálogo 323 (L0.6f) | repetir en otro tren |
| `NetTractiveEffort` HTTP | L0.6d | catálogo | idem |

**¿Para qué serviría RPM al frenar?**

- **323 ahora:** casi nada vía RPM motor. Lo que sí importa al frenar ya está (o está en lab):
  - `train_brake` + `brake_cyl_bar` — freno neumático
  - `dyn_brake` — palanca regen (323 combined)
  - `accel_ms2` — feedback deceleración real
  - `is_slipping` (9b-a) — no bajar freno en zona tracción
  - **L0.6d** — esfuerzo negativo en Simulation (análogo a “estoy frenando de verdad”)
- **Rueda `AngularVelocity_RPM`:** redundante con `speed_ms`; solo interesaría si comparas

  **rueda vs tren** para slip fino sin HUD — baja prioridad (ya tenemos `HUD_GetIsSlipping`).

- **Diesel (paso 10 / SD40):** RPM motor sí — ventana de **dynamic brake** (mín/máx RPM),

  confirmar **idle antes de air brake**, coordinar **notch ↓ → coast → DB → train brake**,
  detectar **motor lug** (RPM cae con power alto). Protocolo lab: F5 en secuencia
  P4 → idle → DB → B2 con `notas_sesion.md`; comparar `Needle1` vs `Needle2` si bimotor.

### L0.6f — amperímetro (`HUD_GetAmmeter`) — **cerrado 323 (catálogo)**

**Guía (otros trenes):** [LAB_CAPTURA_AMPS.md](LAB_CAPTURA_AMPS.md) · `summarize_hud_amps.py`

**Class 323 — conclusión:** la API responde en F5 (Lua = HTTP) pero **`Amps` siempre 0** en las
condiciones probadas, incluida tracción real:

| Sesión | Situación | `Amps` |
| --- | --- | --- |
| `20260830T213100Z`, fixtures | varias | 0 |
| **`20260901T211818Z`** | **~49 mph, P2, accel +0.08** | **0** |

No es fallo del mod: **este vehículo no alimenta el amperímetro HUD** (igual que
`HUD_GetTractiveEffort`).
Frenado en probe 323: `dyn_brake` + `train_brake` + cilindro + `accel_ms2` — sin `amps`.

**Otro tren:** repetir protocolo F5 completo (5 capturas en LAB_CAPTURA_AMPS). Diesel/EMU distinta
puede mostrar `Amps` ≠ 0 → entonces cablear en GetData (D2) **solo para ese `vehicle_class`**.

```bat
```

| Veredicto | Acción |
| --- | --- |
| `variable` | Cablear `amps` en probe (vehículo concreto) |
| `always_zero` | Catálogo para ese vehículo |

### SimulationGraph — qué es (y por qué importa)

En TSW la física del tren no es “un montón de propiedades sueltas” en el actor: es un **grafo de
simulación** (tuberías de aire, cilindros, ejes, compresor, etc.) colgado del componente
`Simulation` del vehículo.

```text
```

| Pieza | Rol aproximado | Lo que vimos en `213100Z` |
| --- | --- | --- |
| **`SimulationComponent`** | Contenedor UE en el actor | `IsValid: true` · funciones `GetSimulation`, `ResetSimulation` |
| **`SimulationGraph`** | Definición del grafo (wiring, tipos de nodo) | Propiedad reflejada; valor = `userdata` (no escalar) |
| **`SimulationGraphInstance`** | Grafo **vivo** con presiones/masas actuales | Idem — candidato a leer en Lua sin tocar hijos inválidos |
| **`sim["BrakeCylinder_2_1"]`** | Acceso por nombre al nodo | `index_ok` pero `IsValid: false` → **no** introspectar con UE4SS |
| **HTTP `.../Simulation/BrakeCylinder_2_1.Pressure_BAR`** | Mismo grafo, API del juego | Funciona; es el canal fiable hoy para L0.6 |

**Por qué `formation.lua` falla y HTTP no:** HTTP recorre el grafo por rutas de texto; UE4SS expone
el componente y handles a nodos, pero los nodos hijos no son `UObject` válidos para
`ForEachProperty`.
Los campos de presión viven **dentro** del `SimulationGraphInstance`, no como `sim.Pressure_BAR` en
la
raíz (el `field_probe` del componente devuelve `userdata` en esos nombres, no números).

**L0.6c cerrado (build `20260830l`):** `graph_probe` confirma que `SimulationGraphInstance`,
`SimulationGraph` y `GetSimulation()` son **válidos** (`SimulationRuntime` / `SimulationAsset`),
pero
los nodos hijo siguen `index_ok` + `child_valid: false` + `fields: {}` en los tres parents. **No**
más
experimentos Lua en hijos Simulation — riesgo crash; canal fiable = HTTP.

### Seguridad `reflect_shallow` — árbol Simulation (Shift+F6)

Build `20260830j` amplió Shift+F6 para reflejar `actor.Simulation` y hijos conocidos. En Class 323
los hijos existen (`index_ok`) pero **`IsValid() == false`**. Llamar `GetClass` / `ForEachProperty`
/
`ForEachFunction` / `GetFullName` sobre esos userdata provoca **crash nativo**
(`EXCEPTION_ACCESS_VIOLATION`
en UE4SS, no capturable con `pcall` Lua).

| Evento | Sesión / build |
| --- | --- |
| Crash TSW | `20260830T205643Z` — último log: `formation` OK; **sin** línea `reflect_shallow` |
| Dump | `%LOCALAPPDATA%/../Documents/My Games/TrainSimWorld6/Saved/Crashes/UE4CC-...` |
| Fix | Build **`20260830k`**: introspección solo si `IsValid`; hijos inválidos → stub `introspection: skipped` |

**Regla para código futuro:** comprobar `obj:IsValid()` antes de cualquier reflect UE4SS.
`lua_probe`
en `formation.json` indica si un nodo es candidato seguro (`child_valid: true`) o solo stub.

Sesión `145544Z` con build `f` salió vacía en `simulation{}` por otra vía (sin `lua_probe`). Builds
`g`–`i` usan `sim[name]` sin exigir `IsValid` en hijo; los campos siguen sin leerse en 323.

### Protocolo L0.4b — catálogo de señales (antes de C1 en probe)

**Estado:** enum numérico **cerrado** en UK Class 323 (DriverAid Lua). Cola `next_signals[]` en Lua
sigue
sin leerse (TArray) — no bloquea C1.

**Campos en Lua (F7):** `signalAspectClass`, `distanceToSignal` (cm), `signalSeen`,
`signalPropertyGuid`,
posición `next_signal_position`. Mismo contenido en `http_guess` (`DriverAid.Data.*`).

#### Tabla aspecto × enum — UK 323 (confirmado in-game 2026-08-31)

| `signalAspectClass` | Aspecto (UK 323) | Sesión lab | Notas |
| --- | --- | --- | --- |
| **0** | Clear / verde | `213100Z`, `145544Z` | `signal_red_candidate: 0` |
| **1** | Caution / ámbar (o double yellow) | `212529Z` (nieve) | Confirmar etiqueta exacta en ruta |
| **2** | **Stop / rojo** | `214213Z` (nieve) | **Confirmado visualmente por operador** |

**Propuesta C1 (probe):** `signal_red=1` si `signalAspectClass == 2` (y `distanceToSignal > 0`).
El explorer hoy solo marca rojo con string `"Stop"`/`"DANGER"` en `probe_candidates` — actualizar al
cablear paso 4 PLAN_V2. `is_red_signal_aspect()` en Python hoy es **string**; añadir rama numérica
`== 2`.

**Distancia:** usar `distanceToSignal` tal cual (cm), igual que `dist_limit_cm` en planning.

#### Protocolo de captura (histórico)

| Fase | Qué hacer | Qué anotar |
| --- | --- | --- |
| 1. **Línea base** | F7 con señal **verde/clear** adelante | `signalAspectClass: 0` |
| 2. **Cola adelante** | F7 en marcha con varias señales visibles | `next_signals[]` en Lua (sigue vacío) |
| 3. **Ámbar** | F7 con caution adelante | `signalAspectClass: 1` (`212529Z`) |
| 4. **Rojo** | F7 con Stop adelante | `signalAspectClass: 2` (`214213Z`) |
| 5. **Conclusión** | Tabla campo × aspecto | ✅ arriba — GetData: `signal_red` + `signal_dist_cm` |

**Autopilot (PLAN_V2 §3):** solo **rojo** entra en P1; ámbar/verde fuera (conductor, D8).

### Masa HTTP — validación composición (paso 9)

| Sesión | Escenario | Coches (manual) | `ClampPowerInput.Mass` | Δ vs Cross-City |
| --- | --- | --- | --- | --- |
| `213100Z` | Cross-City | **3** | **45 550** kg | — |
| `214213Z` | Nieve | **6** | **44 430** kg | **−1 120** kg (más coches, **menos** masa HTTP) |

**Conclusión (cerrada 2026-09-01):** el total HTTP **no** escala con el número de vagones.
**F-B off** — no cablear `mass_factor` en `physics.py`; autopilot `mass_factor = 1.0`. Poll/log HTTP
opcional para diagnóstico.

#### Masa por eje (HTTP `--formation`) — nota freight

Barrido actual (`Axle_1_1`, `Axle_2_1` en el drivable) — mismas cifras en **3 y 6 coches**:

| Nodo | Cross-City | Nieve | Notas |
| --- | --- | --- | --- |
| `Axle_1_1.Mass` | **1 000** | **1 000** | Solo ejes del **coche conducible** |
| `Axle_2_1.Mass` | **1 000** | **1 000** | Idem |
| **Suma 2 ejes** | **2 000** | **2 000** | **No** es peso del tren |
| `ClampPowerInput.Mass` | 45 550 | 44 430 | Total formación |
| `LoadSensingBrakeModifier.Mass` | 4 550 | 3 430 | Δ **−1 120** = mismo Δ que `ClampPowerInput` |

`Mass_kg` en ejes → `{}` vacío. No aparecen ejes de vagones remolcados (6 coches ≠ 12 ejes en
probe).

**Utilidad freight (paso 10 / F-D):** antes de confiar en masa por eje en SD40, ampliar
`formation.lua` /
`FORMATION_PROBE_SPECS` para listar **todos** los `Axle_*` (o nodos por coche) en
`CurrentFormation/0/…` y `CurrentFormation/N/…`, sumar `Mass` y contrastar con
`ClampPowerInput.Mass`.
Hipótesis: en mercancías con muchos vagones la suma por eje **sí** podría cuadrar; en EMU 323 el
probe solo ve el drivable. **Experimento futuro** — no bloquea P1 pasajeros.

#### Catálogo RailBridge — `tsw-api-export-Simulation-20260830T003506Z.json`

Dump HTTP del subárbol **`CurrentDrivableActor/Simulation`** (un solo coche, no formación completa).
Útil como **índice de nombres**; valores de esa captura ≠ sesiones lab posteriores.

| Ruta HTTP | Valor (dump 30-ago) | Notas |
| --- | --- | --- |
| `ClampPowerInput.Mass` | **41 000** | Total agregado (≠ 45 550 Cross-City / 44 430 nieve en juego) |
| `Bogie_1.Mass` / `Bogie_2.Mass` | **5 000** c/u | **No** en probe `formation` actual — candidato freight |
| `Axle_1_1` … `Axle_2_2.Mass` | **1 000** × 4 | 4 ejes en drivable (lab solo leía `_1_1` y `_2_1`) |
| `LoadSensingBrakeModifier.Mass` | **0** | En partida suele ser ≠ 0 y seguir Δ del total |
| Suma bogies+eje | 14 000 | **No** = `ClampPowerInput` — no usar suma simple |

No aparece `CurrentFormation/N/…` en este export (solo drivable). Para peso de **toda** la formación
sigue siendo `CurrentFormation/0/Simulation/ClampPowerInput.Mass` en vivo.

### Mapa cableado — lab → archivo destino (documentación; **sin cablear** aún)

Regla del plan: explorer **propone** en JSON; el código de producción adopta tras revisión (D2).

| Dato (origen lab) | Archivo / módulo destino | Qué haría al cablear | Paso | |
| --- | --- | --- | --- | --- |
| `signalAspectClass` + `distanceToSignal` (F7) | `mods/TelemetryProbeMod/Scripts/main.lua` | `extract_signal_red()` → línea GetData | 4 | |
| `signal_red`, `signal_dist_cm` | `docs/CANAL_CONTROL.md` (contrato) | Schema GetData | 1 | |
| ↑ mismo | `tsw6/telemetry/tsw_ue4ss_reader.py` | `parse_probe_line` / `ProbeSnapshot` | 4 | |
| ↑ mismo | `tsw6/braking/v2/objectives.py` | `is_red_signal_aspect` (+ enum `== 2`) | 4–5 | |
| ↑ mismo | `tsw6/braking/v2/coordinator.py` | P1 emergencia señal | 5 | |
| `HUD_GetIsSlipping` (F5) | `mods/TelemetryProbeMod/Scripts/main.lua` | `build_line` → `is_slipping=0\ | 1` | 9b-a |
| `HUD_GetIsTractionLocked` (F5) | idem | opcional `traction_locked=0\ | 1` | 9b-a |
| ↑ mismo | `tsw6/telemetry/tsw_ue4ss_reader.py` | parser (ya stub) | 9b-a | |
| Handler slip (matriz S1–S4) | `tsw6/autopilot/` o `handle_controller.py` | solo tras estudio | 9b-b | |
| `controls.json` → G-B | `data/vehicles/class_323.json` | ✅ generado | 7 ✅ | |
| ↑ mismo | `tsw6/learning/control_layout.py` + IPC | leer paquete al mandar | 6 | |
| `ClampPowerInput.Mass` HTTP | ~~`tsw6/telemetry/tsw_telemetry_source.py`~~ | poll log opcional | 9 **off** | |
| ↑ mismo | ~~`tsw6/braking/v2/physics.py`~~ | ~~`mass_factor`~~ **no usar** | 9 **off** | |
| Masa bogies / multi-eje | `mods/ApiExplorerMod/Scripts/formation.lua` + correlator | ampliar probe; freight | 10 | |
| F9 / reflect en probe | `mods/TelemetryProbeMod/Scripts/main.lua` | **borrar** ~300–500 líneas | depuración | |
| Validación HUD vs probe | `scripts/tools/compare_lab_vs_probe.py` | herramienta manual | L0.8 ✅ | |
| Correlator HTTP | `scripts/tools/api_correlator.py` | `--formation`, HUD | L0.5 ✅ | |

**Van al probe (323):** `HUD_GetBrakeGauge_1` → `brake_cyl_bar` (build `20260905b`).

**No van al probe (323):** `HUD_GetAmmeter` y
`HUD_GetTractiveEffort` (**catálogo** L0.6f/L0.6d); `NetTractiveEffort` HTTP; `http_guess` completo;
`reflect_shallow.json`.

### Patinaje — canal HUD (paso 9b)

| Fuente | Campo | Evidencia |
| --- | --- | --- |
| **F5 `hud_batch`** | `HUD_GetIsSlipping` → `IsSlipping` | `214213Z`: **`true`** en marcha (~24 m/s, nieve) |
| **F5 `hud_batch`** | `HUD_GetIsTractionLocked` | `214213Z`: **`true`** mismo instante |
| **F5 parado** | ambos `false` | `213100Z`, `212529Z` — no sirve para estudiar slip |
| **HTTP `--formation`** | `Axle_*.CurrentTrackAdhesion` | `214213Z` ~0,01 vs Cross-City ~0,99 |
| **HTTP `--formation`** | `Axle_*.IsSlipping` | Puede quedar `false` aunque HUD marque slip (instante distinto) |

**Reglas de producto** (no cambian): ver [PLAN_V2 §2
Adherencia](PLAN_V2.md#adherencia--canal-hud-validado-lab-20260830t213100z) —
**9b-a** emitir `is_slipping` en GetData (solo log); **9b-b** handler P1 solo tras matriz S1–S4.
Matriz borrador: no actuar parado; no actuar fuera de APPLY; en zona freno + slip → soltar 1 muesca
(debounce).

---

### Desbloqueos respecto a PLAN_V2

| Paso PLAN_V2 | Explorer previo |
| --- | --- |
| 1 cerrado (C1 en probe) | L0.4 ✅ escalares; L0.4b ✅ enum `0/1/2` + distancia Lua |
| 6 paquete JSON G-B | L0.3 ✅ sesión referencia → L0.7 |
| Depuración probe | L0.1–L0.2 ✅ — candidato quitar F9 en probe |

---

## Qué NO hacer

- Escribir en `%TEMP%\TSW6Bridge\`
- Registrar el mismo `ReceiveTick` que el probe (doble hook / hitch)
- Añadir campos a GetData desde el explorer (solo propuesta en doc + JSON)
- Unificar mods en un solo `main.lua`
- Crawler HTTP dentro de Lua (lento; usar Python con `-HTTPAPI`)
- Introspección UE4SS (`GetClass`, `ForEachProperty`, `GetFullName`) sobre UObject con `IsValid ==

  false`
  (crash nativo; ver § reflect Simulation)

---

## Criterios de éxito

| # | Criterio |
| --- | --- |
| 1 | Probe puede desactivar F9 sin perder capacidad de investigación |
| 2 | `class_323.json` generable desde exports sin editar probe | ✅ L0.7 |
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
| 2026-08-31 | **L0.7** `vehicles_json_from_lab.py` → `data/vehicles/class_323.json` |
| 2026-08-31 | **L0.8** fixtures `tests/fixtures/lab/` + `compare_lab_vs_probe.py` + `test_lab_serialize.py` |
| 2026-08-31 | **L0.4b** enum señales UK 323: `0` clear · `1` ámbar · `2` rojo (`212529Z`/`214213Z`) |
| 2026-09-01 | **Masa vs vagones:** 3 coches / 45 550 kg vs 6 / 44 430 kg — **F-B off** |
| 2026-09-01 | **Masa por eje:** `Axle_*` = 1 000+1 000 kg (igual 3/6 coches); nota freight ampliar probe |
| 2026-09-01 | **L0.6d cerrado** — tracción HTTP `210515Z` (+651 N); HUD/Lua 0 — no probe |
| 2026-09-01 | **L0.6f kit** — `LAB_CAPTURA_AMPS.md` + `summarize_hud_amps.py` |
| 2026-09-01 | **L0.6e** RPM motor vs rueda — útil diesel; 323 usar dyn_brake/ammeter, no EngineRPM |
| 2026-09-01 | **L0.6f cerrado 323** — `211818Z` Amps=0 con P2 @ 49 mph; repetir en otro tren |
| 2026-09-01 | Plan: índice, resumen ejecutivo 323, tabla sesiones, coherencia L0.6 |

---

## Referencias

| Archivo | Relación |
| --- | --- |
| `data/lab_exports/exports/20260901T210515Z/` | L0.6d HTTP tracción +651 N |
| `data/lab_exports/exports/20260901T211818Z/` | L0.6f 323: Amps=0 con tracción; barrido L0 completo |
| [LAB_CAPTURA_F5.md](LAB_CAPTURA_F5.md) | Qué recopila F5, protocolo frenar/acelerar |
| [LAB_CAPTURA_AMPS.md](LAB_CAPTURA_AMPS.md) | Protocolo amperímetro — **repetir en cada tren nuevo** |
| `data/lab_exports/exports/20260830T213100Z/` | **Sesión referencia 323** Cross-City (L0 + HTTP, build `l`) |
| `data/lab_exports/exports/20260831T214213Z/` | Nieve: rojo enum **2**, slip HUD, masa **44 430** kg |
| `data/lab_exports/exports/20260831T212529Z/` | Nieve: ámbar enum **1** |
| `data/lab_exports/exports/20260830T211527Z/` | Complementaria reflect estable (build `k`) |
| `data/lab_exports/exports/20260830T145544Z/` | Histórica HUD en marcha + pytest mock |
| [PLAN_V2.md](PLAN_V2.md) | Producto v2, probe §4.1, G-B §1, C1 §3 |
| [CANAL_CONTROL.md](../CANAL_CONTROL.md) | Contrato GetData (D2) — destino de campos aprobados |
| `Desktop\investigacion tsw 6\apis\tsw-api-export-Simulation-*.json` | Catálogo HTTP Simulation (Mass, bogies, ejes) |
| [CURRENTFORMATION_API.md](../reference/CURRENTFORMATION_API.md) | Catálogo HTTP física / HUD |
| [DRIVERAID_API.md](../reference/DRIVERAID_API.md) | Vía, señales, planning |
| [DRIVERINPUT_API.md](../reference/DRIVERINPUT_API.md) | Escritura mandos / nombres lever |
| `mods/TelemetryProbeMod/Scripts/main.lua` | Probe actual (no mezclar) |
| `mods/ApiExplorerMod/Scripts/` | Mod laboratorio (este plan) |
| `scripts/tools/api_correlator.py` | L0.5 HTTP ↔ `http_guess` |
| `scripts/tools/vehicles_json_from_lab.py` | L0.7 G-B `controls.json` → `data/vehicles/` |
| `scripts/tools/compare_lab_vs_probe.py` | L0.8 `hud_batch` ↔ GetData |
| `scripts/tools/summarize_hud_amps.py` | L0.6f amperímetro — tabla + `amps_report.md` |
| `tests/fixtures/lab/` | Fixtures pytest (sesión `213100Z`) |
| `data/vehicles/class_323.json` | Paquete G-B 323 (sesión `213100Z`) |
| `scripts/ue4ss/install_ue4ss_explorer.bat` | Instalador UE4SS |

### Correlator (L0.5)

```bat
```

Con TSW6 en marcha y `-HTTPAPI`: escribe `correlation_report.md` en la carpeta de sesión.
`--formation` escribe además `formation_http.json` y `formation_report.md` (L0.6 híbrido).

### Amperímetro (L0.6f)

```bat
```

### Compare probe (L0.8)

```bat
```

### Paquete G-B (L0.7)

```bat
```
