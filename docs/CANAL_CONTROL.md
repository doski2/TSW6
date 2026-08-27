# Canal de control — plan de fases

Documento de arquitectura para corregir el cuello de botella IPC/mandos antes de
retomar trabajo en P1, learner o planner.

**Última revisión:** 2026-08-27 — B.8 **canal PASS** / P1 **no PASS** (`autopilot_20260827_192303.log`); siguiente = Fase C  
**Relacionado:** [FLUJO_FRENOS.md](FLUJO_FRENOS.md) · [ESTADO.md](ESTADO.md) ·
[ARQUITECTURA.md](ARQUITECTURA.md) · `tsw6/telemetry/channel_diagnostics.py` · `install_ue4ss_probe.bat`

---

## Lua probe ≠ HTTP API

El mod `mods/TelemetryProbeMod/Scripts/main.lua` **no llama a HTTP**. Usa la carpeta
`%TEMP%\TSW6Bridge\` como **puente** entre Python (autopilot) y el juego (UE4SS):

| Archivo | Quién escribe | Quién lee | Contenido |
| --- | --- | --- | --- |
| `GetData.txt` | **Lua** (~20 Hz) | **Python** | Telemetría (`speed_ms`, `lever_notch`, …) — **overwrite** mismo fichero cada ciclo (`io.open` modo `"w"`) |
| `SendCommand.txt` | **Python** | **Lua** | Línea de mando (`PowerBrakeHandle:0.3750:42`) |
| `TSW6ApplyCommands.flag` | **Python** | **Lua** | “Hay mandos armados” (evita órdenes huérfanas) |
| `SendCommandAck.txt` | **Lua** | **Python** | Resultado (`PowerBrakeHandle:0.3750:ok:42` o `:fail:`) |

**Lua no escribe los mandos en el puente** — los **recibe**, los aplica en el motor UE
(`SetCurrentOutputValue` en `PowerBrakeHandle`) y devuelve ACK. Esa es la idea del canal IPC.

Dentro del juego, el Lua solo usa:

1. **Ficheros del puente** (tabla arriba).
2. **UE4SS en proceso** — `controller` → `GetDrivableActor()` → `PowerBrakeHandle`, etc.
3. **Escritura nativa UE** — `SetCurrentOutputValue(muesca − 4)` en Class 323 (no HTTP, no `InputValue`).

No hay sockets, URLs, `PATCH`, ni cliente HTTP **en el Lua**.

```text
Python autopilot                          Lua (UE4SS en TSW)
     │                                          │
     │  escribe SendCommand.txt + flag          │
     ├─────────────────────────────────────────►│ lee mandos
     │                                          │ aplica en UObject (palanca)
     │  lee GetData.txt ◄───────────────────────┤ escribe telemetría
     │  lee SendCommandAck.txt ◄────────────────┤ escribe ok/fail
     │                                          │
     └─► HTTP :31270 (solo Python, fallback)    └─► sin HTTP
```

| Concepto | Lua (probe) | HTTP API (Python) |
| --- | --- | --- |
| Transporte | Ficheros en `%TEMP%\TSW6Bridge\` | `PATCH /set/...` en `:31270` |
| Quién escribe mandos al tren | **Lua** (tras leer `SendCommand.txt`) | **Python** vía HTTP PATCH si IPC falla |
| Ruta `DriverInput/PowerBrakeHandle` | **No existe** como llamada HTTP | Namespace virtual del catálogo HTTP |
| Búsqueda en Lua | `try_child(actor, "PowerBrakeHandle")`, `FindAllOf(IrregularLeverComponent)`, etc. | N/A |
| Escala del mando en línea IPC | `cmd` 0..1 (`muesca/8`) en `SendCommand.txt` | HTTP palanca **no** es el canal de producción |

**Importante:** `cmd=0.375` en log Lua es la línea IPC (destino muesca 3), no HTTP.
Lua da **un paso** de HUD hacia ese destino y escribe **salida** `muesca − 4` (no el eje InputValue).

### Class 323 (UK) — IPC **validado** 2026-08-27 17:13

| Dato | Valor |
| --- | --- |
| Estado | ✅ HUD y tren responden; `last_ack_ok=1`; un paso por IPC |
| Build probe | `20260828a` |
| Objeto UE | `…PowerBrakeHandle` (`IrregularLeverComponent`) |
| UFunction | `SetCurrentOutputValue` (escala potencia **−4…+4** = `muesca − 4`) |
| `Notches` (InputValue) | 9 detentes irregulares −1…1 (tabla abajo); **no** usar este eje en OutputValue |
| Contrato | Python manda destino 0..1; Lua aplica **HUD ± 1**; ACK si el HUD se acerca |
| Fallback | Teclado A/D si ACK fail — **sin** PATCH HTTP de palanca |

| HUD | Palanca | InputValue (`Notches`) | Output (`SetCurrentOutputValue`) |
| --- | --- | --- | --- |
| 0 | B4 | −1.00 | −4 |
| 1 | B3 | −0.60 | −3 |
| 2 | B2 | −0.40 | −2 |
| 3 | B1 | −0.20 | −1 |
| 4 | costa | 0.00 | 0 |
| 5 | P1 | 0.25 | +1 |
| 6 | P2 | 0.50 | +2 |
| 7 | P3 | 0.75 | +3 |
| 8 | P4 | 1.00 | +4 |

**No mezclar escalas:** `SetCurrentOutputValue(0.25)` (eje P1) se interpreta como potencia ≈ 0 → costa. Eso era el salto 6→4.

**Prueba solo IPC:** `iniciar_monitor.bat` → **`test-ipc`**. PASS: `out step=…` y `lever_notch` cambia **una** muesca (`hud 6->5`, luego `5->4` en id=2).

### test-ipc 2026-08-27 17:13 (build `20260828a`) — **PASS**

```text
IPC SetCurrentOutputValue out step=5 axis=1.0000 dest=3 → ok hud 6->5
PBH write OK … last_ack_ok=1  power=1  lever_notch=5
IPC SetCurrentOutputValue out step=4 axis=0.0000 dest=4 → ok hud 5->4
power=0  lever_notch=4
```

Mapa `PBH map ready entries=9`. Sin `WARN skip`.

**Prueba cadena palanca:** `test-ipc` (Lua) y autopilot con TSW en primer plano (teclado si Lua falla).
No usar `test-brake` para mandos (esa ruta es HTTP y queda fuera del canal de control).

Opcional: **F9** en cabina vuelca funciones/propiedades (`=== Reflect PBH`).

### test-ipc 2026-08-27 08:48 (build `20260827o`) — FAIL, sin crash

```text
IPC recv PowerBrakeHandle=0.3750 id=1 build=20260827o
IPC direct PBH UObject: … [IrregularLeverComponent] cmd=0.3750 notch=3
IPC write PBH InputValue=-0.2500
PBH readback InputValue=nil OutputValue=nil hud=6
WARN direct PBH set=0.3750 failed: no_effect
last_cmd_id=1 last_ack_ok=0  lever_notch=6
```

Segundo mando id=2 (neutro) igual. El canal IPC está sano; `ctrl.InputValue = eje` no es el actuador.
`GetFullName():ToString()` fallaba (el log solo mostraba puntero) — corregido en `p` (`lua_str`).

**Build `20260827p`:** F9 / primer IPC listan UFunctions (`ForEachFunction`) y prueban hasta 3
setters vía `ProcessEvent` (nunca `SetCurrentNotchIndex` / `SetInputValue` / `ConditionalBeginTick`).

### test-ipc 2026-08-27 08:57 (build `20260827p`) — FAIL, sin crash; reflect útil

Objeto correcto (ya no es un puntero opaco):

```text
…PersistentLevel.RVM_BCC_WRM_Class323_DMS_A_C_2147380436.PowerBrakeHandle
class: IrregularLeverComponent
```

| Qué | Resultado |
| --- | --- |
| IPC id=1 y id=2 | ✅ `last_cmd_id` sube |
| `ctrl.InputValue = eje` | ❌ `readback InputValue=nil` — **la propiedad no está en el UClass** |
| `ProcessEvent SetCurrentInputValue` / `SetNormalisedInputValue` | ❌ sin línea `PE … pcall=ok` → `GetFunction`/`ProcessEvent` falló (params mal nombrados) o no aplicó |
| HUD / `lever_notch` | ❌ sigue en **6** (tracción P2); objetivo era 3 luego 4 |
| Crash | ✅ no |

Jerarquía y campos relevantes del dump:

```text
IrregularLeverComponent
  ValueMap, Notches
LeverBaseComponent
  GetCurrentNotchIndex          ← existe; SetCurrentNotchIndex NO está (el crash de `m` era un método Lua inventado)
  TargetInputValue, TargetOutputValue, CurrentNotchID
  IncreaseInputs, DecreaseInputs, DigitalInteractionMode
VirtualHIDComponent
  SetCurrentInputValue, SetNormalisedInputValue, SetCurrentOutputValue
  SetPositionDeltaAnalogue, BeginIncreaseDigital, BeginDecreaseDigital
  BeginChangingAnalogue, EndChanging, InputValueChanged
  CurrentInputValue, CurrentOutputValue   ← FloatProperty reales
  bInputEnabled, bIsChanging
```

**Por qué falló `p`:** Lua escribía `InputValue` (nombre CommAPI/HTTP). En UE el eje es `CurrentInputValue` / `TargetInputValue`. `ProcessEvent` se llamó con tablas `{InputValue=…}`; el UFunction espera otro nombre de parámetro (casi seguro `CurrentInputValue` o similar), así que no hay `PE pcall=ok` y el HUD no cambia.

**Siguiente write (sin APIs de crash):**

1. Asignar `CurrentInputValue` y `TargetInputValue` (FloatProperty visibles).
2. `ProcessEvent("SetCurrentInputValue", { CurrentInputValue = eje })`.
3. Si hace falta el mismo camino que A/D: `BeginIncreaseDigital` / `BeginDecreaseDigital` (un paso por mando).
4. No llamar `GetCurrentNotchIndex` ni `ConditionalBeginTick`.

**Build `20260827q`:** asigna `CurrentInputValue` y `TargetInputValue`; `ProcessEvent` con
`{ CurrentInputValue | NewValue | NewInputValue }` y `SetNormalisedInputValue` (eje 0..1).
Log: `PBH readback CurrentInput=…` y `IPC PE … → ok|no_fn|pe_fail`.

### test-ipc 2026-08-27 09:12 (build `20260827q`) — ACK falso; palanca no se mueve

```text
IPC write PBH CurrentInputValue=-0.2500
readback CurrentInput=-0.25 TargetInput=0.5 NotchID=6 hud=6
PBH write OK via CurrentInputValue   hud 6->6
last_ack_ok=1   lever_notch=6
```

Lua **sí pega** `CurrentInputValue`. `TargetInputValue` se queda en **0.5** (muesca 6) y el HUD no cambia.
El ACK `ok` era un falso positivo (se daba por coincidir el float). Corregido en `r`.

### Crash 2026-08-27 08:31 (build `20260827n`)

GUID `UE4CC-Windows-006BBDBD49F0D173391D13A9631B57F2`. Mismo `PCallStackHash` que build `m`
(`EXCEPTION_ACCESS_VIOLATION` lectura `0x20` en UE4SS.dll). `UE4SS.log` termina en `seq=102` con
`last_cmd_id=0` — sin líneas `IPC write`/`IPC recv`; el juego murió al primer mando `test-ipc`.

**Causa probable en `n`:** durante `collect_control_candidates` / primer write, Lua tocaba UObject
de forma amplia (`GetCurrentNotchIndex`, `ConditionalBeginTick`, `write_simulation_brake`, o
`pairs(actor)`). `pcall` no atrapa AV nativos en UE4SS.

**Build `20260827o`:** ruta **directa** `drivable.PowerBrakeHandle` → solo `InputValue` (eje);
sin búsqueda de candidatos ni fallback Simulation en modo SAFE; log `IPC recv` antes de escribir UE.

### Estado sesión 2026-08-27 01:48 (Class 323, build `20260827j`)

Logs: `autopilot_20260827_014810.log` + `UE4SS.log` (23:47–23:49 local).

| Criterio | Resultado |
| --- | --- |
| Telemetría probe ~20 Hz | ✅ `frozen=N`, Class 323 en cabina |
| IPC entrega mandos | ✅ `last_cmd_id` 0→38+; líneas `IPC delegate … → HTTP` en UE4SS |
| Sin crash UE4SS | ✅ (modo `IPC_DELEGATE_HTTP`, sin `FindAllOf`) |
| ACK honesto | ✅ `lua_rejected` / `last_ack_ok=0` (delegate intencional) |
| Fix `http_ok` falso | ✅ `http_ok=0` — ya no cuenta PATCH sin efecto |
| HTTP fallback | ❌ `api_error msg=Not Set` en cada intento |
| `lever_notch` / HUD | ❌ fijo en **4** durante toda la fase P1 (objetivo 3→2→1) |
| `match_hb` | ❌ 0 |
| `SESIÓN CANAL` | ❌ **FAIL** — `ipc_ok=0 http_ok=0 total_ok=0/46` |

**Interpretación:** el canal **sí recibe mandos** (IPC ≠ palanca movida). Lua hace su parte
(delegate + ACK `:fail:`). Python intenta HTTP y la CommAPI responde `Result: Error` /
`Message: Not Set` — el nodo `DriverInput.PowerBrakeHandle` no acepta escritura externa en
ese momento (interlock cabina, MCB, master key, o API no enlazada al actuador activo).

Ejemplos correlacionados:

```text
UE4SS:  IPC delegate PowerBrakeHandle=0.3750 id=3 notch=3 → HTTP (sin write UE)
        lever_notch=4 last_cmd_id=3 last_ack_ok=0

Python: HTTP mandos falló PowerBrakeHandle=0.375 — api_error msg=Not Set
        heartbeat … match=N lever=4 hud=4 err=lua_rejected
```

Al cerrar sesión: cola IPC llena (`drops=10`), luego `connection_refused` (juego cerrado).

**Siguiente paso:** `iniciar_monitor.bat` → modo **`test-brake`** (mismo `dispatch_combined_notch`
que el autopilot). Si sigue `Not Set`, revisar `MasterKey`, `MCB_TrainBrake` o dump F9 (B.7).

### Estado sesión 2026-08-27 01:18 (Class 323)

| Criterio | Resultado |
| --- | --- |
| Fix ACK optimista | ✅ `lua_rejected` visible en log |
| HTTP fallback dispara | ✅ pero `lever=4` sin cambio |
| Causa HTTP sin efecto | ❌ PATCH a `PowerBrakeHandle` (ruta corta) — corregido → `DriverInput.PowerBrakeHandle` |
| `frozen=Y` falso | ❌ usaba dist. al cartel (2495 m fija) — corregido → odómetro/velocidad |
| `match_hb=0` | ❌ mando no llegó al HUD |

**Build `20260827m`:** crash `EXCEPTION_ACCESS_VIOLATION` al llamar `SetCurrentNotchIndex` — retirado en `n`.

**Build `20260827n`:** mismo crash stack que `m` sin `SetNotch` — retirado en `o` (ver crash 08:31).

**Build `20260827l`–`m`:** `IPC_DELEGATE_HTTP=false`; `m` añadió actor-first + SetNotch (crash).

### Crash 2026-08-27 01:36 (build 20260827h)

`EXCEPTION_ACCESS_VIOLATION` en UE4SS al primer `SendCommand` — `FindAllOf(IrregularLeverComponent)`.
Juego murió → telemetría congelada, HTTP `connection_refused`.

### Estado sesión 2026-08-27 01:11 (Class 323)

| Criterio CANAL_CONTROL | Resultado |
| --- | --- |
| Probe ~20 Hz, `lever_notch` lectura | ✅ |
| IPC entrega mandos (`last_cmd_id` sube) | ✅ |
| Lua encuentra `IrregularLeverComponent` | ✅ |
| `ctrl.InputValue = eje` mueve HUD | ❌ `no HUD change` |
| `last_ack_ok=1` | ❌ 0 % |
| `SESIÓN CANAL [PASS]` | ❌ FAIL (ipc 2 %, match=N) — **ipc_ok 100 % era falso positivo** (corregido) |

**Bloqueo (histórico, sesión 01:11):** `InputValue` no movía el HUD. Resuelto: `SetCurrentOutputValue` (build `20260828a`).

### Bug corregido: IPC ok falso positivo

Si Lua borraba `SendCommand.txt` y escribía `:fail:`, Python devolvía `IPC ok` optimista sin leer el ACK.
Resultado: `ipc_ok=60/60` con `lever=4` y `match=0`. Corregido en `wait_send_ack` (ya no asume OK al
consumir el fichero de mando).

---

## Estrategia actuador — decisión (sin HTTP en mandos)

**Decisión:** los mandos **no** usan HTTP/CommAPI. Cadena:

```text
Python  →  SendCommand.txt  →  Lua (intento UE, ACK honesto)
                 │  fail / no HUD
                 ▼
            Teclado A/D   (TSW en primer plano; un paso, esperar GetData)
```

HTTP (`-HTTPAPI`) queda **solo** para planning/estaciones (DriverAid), no para la palanca.

| Capa | Rol | Estado Class 323 |
| --- | --- | --- |
| IPC fichero | Bus de mandos + telemetría | ✅ entrega y GetData ~20 Hz |
| Lua UObject | Palanca Class 323 | ✅ `SetCurrentOutputValue(muesca−4)`; `test-ipc` PASS |
| Teclado A/D | Fallback si ACK Lua `fail` | ✅ sí mueve la palanca |
| HTTP CommAPI | **No se usa para mandos** | — |

**Por qué teclado y no HTTP:** CommAPI responde `Not Set` en el Class 323 y el usuario no quiere PATCH de palanca. El teclado usa el mismo camino que el jugador (`IncreaseInputs` / digital). TSW debe estar en **primer plano**.

**Criterio de verdad:** `last_ack_ok=1` **solo** si HUD o `CurrentNotchID` cambian (build `r`). Tras `lua_rejected`, Python pasa a A/D (`prefer_keyboard_actuator`).

**Cómo probar:**

1. `install_ue4ss_probe.bat` → build `20260828a` → reiniciar TSW.
2. `test-ipc` — `out step=` y HUD ±1.
3. Autopilot (B.8) — P1 por IPC; `KEY` solo si ACK fail.

Cuando Lua tenga `last_ack_ok=1` y `lever_notch` coincida, se puede apagar el teclado en P1.

### Cómo manda comandos UE4SS Lua (docs oficiales)

Fuente: [UObject](https://docs.ue4ss.com/lua-api/classes/uobject.html), [UFunction](https://docs.ue4ss.com/lua-api/classes/ufunction.html), [Creating a Lua mod](https://docs.ue4ss.com/dev/guides/creating-a-lua-mod.html).

| Mecanismo | Uso correcto | Lo que hicimos mal |
| --- | --- | --- |
| Leer/escribir campo | `obj.Prop` / `obj.Prop = x` o `SetPropertyValue` | `InputValue` no existe; `CurrentInputValue` sí pero el tren ignora el espejo |
| Llamar UFunction | **dos puntos y args posicionales:** `obj:CanJump()`, `obj:SetCurrentInputValue(eje)` | `ProcessEvent(fn, { CurrentInputValue = eje })` no es la API Lua |
| UFunction sin contexto | `fn(objeto, args…)` si se obtuvo con `StaticFindObject` | — |
| Hilo | `ExecuteInGameThread` (o ya estar en `ReceiveTick`) | El probe ya corre en el hook del tick |
| Out-params | pasar `{}` y leer `t.NombreParam` ([issue #368](https://github.com/UE4SS-RE/RE-UE4SS/issues/368)) | — |

Build `s` llama `SetCurrentInputValue(eje)`, `SetNormalisedInputValue(0..1)`, `SetPositionDeltaAnalogue(delta)` y un paso `BeginDecreaseDigital`/`BeginIncreaseDigital`. Dump `ufn-param` en el log.

### Sesión 2026-08-27 11:48 — sin mandos IPC

`UE4SS.log` solo telemetría (`seq` sube, `lever_notch=6`, **`last_cmd_id=0`**). No hay `IPC recv`. El probe estaba ON; **Python no escribió `SendCommand.txt`** (o el flag Lua no armó mandos). Para probar Lua hace falta `test-ipc` o autopilot con probe armado.

### Meta a medio plazo (Lua puro, sin crash)

| Enfoque | Estado | Notas |
| --- | --- | --- |
| `ctrl.InputValue = eje` | ❌ no existe en UClass | Nombre CommAPI |
| `SetCurrentNotchIndex` / `SetInputValue()` / `ConditionalBeginTick` | ❌ crash | No reactivar |
| `CurrentInputValue` assign | 🟡 `q` | Se pega; HUD no |
| `TargetInputValue` assign | ⬜ `r` | En `q` no se llegó (ACK falso) |
| `ProcessEvent(fn, {Nombre=val})` | ❌ no es la API Lua | Docs: no hay ese contrato |
| `obj:UFunction(args)` / `CallFunction` | 🟡 build `s` | [UObject Lua API](https://docs.ue4ss.com/lua-api/classes/uobject.html) |
| `BeginIncreaseDigital` / `BeginDecreaseDigital` | 🟡 build `s` | Un paso; equivalente A/D |
| HTTP palanca | ❌ fuera | No PATCH de mandos |
| Teclado A/D | ✅ | Fallback |

### Cómo validar el próximo intento

**Autopilot** (`logs/autopilot_*.log`):

```text
Lua no mueve palanca (IPC lua_rejected) — mandos vía teclado A/D
KEY  APPLY        notch 6→5  (obj=3  D  … fallback)
```

**UE4SS** (`UE4SS.log`):

```text
PBH readback InputValue=-0.2500 OutputValue=... hud=3
IPC write PBH interact+InputValue=-0.2500 ...
```

| Señal | Interpretación |
| --- | --- |
| `KEY` + `match=Y` | P1 vía teclado; TSW en primer plano |
| `PBH readback` cambia pero `hud=` igual | UObject escrito pero simulación no enganchada |
| Solo `WARN ... no HUD change` | Lua no actúa; debe seguir teclado, no HTTP |
| Crash tras quitar `SAFE_LEVER_WRITE` | Volver a modo seguro |

### Criterios B.8 (sesión P1 Class 323)

P1 es `ipc_only`: si Lua falla no hay A/D en esa rama (`p1rej`). `test-ipc` no sustituye esta sesión.

| Criterio | Umbral |
| --- | --- |
| `loop_hz` / `telem_poll` | ≥ 18 / ≥ 15 Hz |
| `ipc_ok` | ≥ 95 % |
| `KEY` en P1 | 0 (WARN si `KEY>0` en acciones no-P1) |
| `p1rej` | 0 |
| `lever_notch` | ±1 muesca en &lt; 1 s tras cada IPC |
| Actuador | `last_ack_ok=1` Lua; teclado solo fuera de P1 o ACK fail; nunca HTTP palanca |

---

### F9 — dump de controles cabina

Tecla **F9** en juego vuelca al log UE4SS qué objetos de mando encuentra el probe en el actor
(no es un dump HTTP). Útil si `last_ack_ok=0` tras instalar build `20260827g`.

Otros trenes (freight NA, freno independiente/automático, etc.) requerirán alias y estrategia
distinta en `CONTROL_ALIASES` — sin mezclar HTTP en el Lua.

---

## Diagnóstico (resumen)

| Síntoma en log | Causa real |
| --- | --- |
| `hz=427` en heartbeat | **No** es frecuencia del bucle — es `1/mean(tick_work)` |
| `tgt=10Hz` | Objetivo real del bucle Python (GUI usa 20 Hz tras Fase A) |
| `tick=2787ms` | Bucle **bloqueado** esperando ACK IPC síncrono |
| `IPC falló` + `KEY notch 4→3` | Teclado incremental — **esperar** `lever_notch` en GetData entre pulsaciones |
| `age=10s` `seq` congelado | Bucle colapsado; telemetría no se lee |
| `ipc=OK` en cycle | Significa “encoló mando”, no que la palanca se movió |
| `IPC ok id=N` en log | ACK Lua `ok` — verificar `match=` / `lever` (no hay fallback HTTP de mandos) |
| `handle_notch` | Derivado de HUD Power; usar `lever_notch` para palanca real |
| `cf=N` pero `match=Y` | ACK IPC falló o tardó; palanca sí llegó vía GetData |
| `ack_timeout` al 100 % | Mod no cargado, ACK no leído a tiempo, o timeout &lt; latencia real |

---

## Fase 0 — Instrumentación (hecho)

| ID | Tarea | Estado |
| --- | --- | --- |
| 0.1 | Métricas canal en log autopilot (`channel_diagnostics.py`) | ✅ |
| 0.2 | Penalización IPC 300 s → 5 s + reintentos | ✅ |
| 0.3 | Heartbeat honesto: `loop_hz`, `work_ms`, `sleep_ms` | ✅ |
| 0.4 | Documento de fases (este archivo) | ✅ |

**Criterio de aceptación Fase 0:** una sesión de autopilot con veredicto `canal [PASS]` o
`SESIÓN CANAL … [PASS]`: p95 ACK &lt; 200 ms, &gt; 95 % IPC OK, `KEY=0` en P1,
`loop_hz` ≥ 18, sin ticks `work` &gt; 150 ms.

---

## Fase A — Canal no bloqueante (hecho)

Separar **lectura**, **escritura** y **decisión** en ritmos distintos.

```text
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ TelemetryReader │     │ AsyncCommandWriter│     │ ControlLoop     │
│ hilo 20 Hz      │     │ hilo + cola       │     │ 20 Hz (GUI)     │
│ lee GetData.txt │     │ IPC + ACK         │     │ decide + encola   │
│ snapshot atómico│     │ nunca bloquea tick│     │ nunca espera ACK  │
└────────┬────────┘     └────────┬─────────┘     └────────┬────────┘
         │                       │                          │
         └───────────────────────┴──────────────────────────┘
                    TswTelemetrySource + CommandState
```

| ID | Tarea | Estado |
| --- | --- | --- |
| A.1 | `TelemetryReader` — hilo 20 Hz | ✅ |
| A.2 | `AsyncCommandWriter` — cola IPC | ✅ |
| A.3 | Integrar en `TswTelemetrySource` | ✅ |
| A.4 | `HandleController` encola mandos | ✅ |
| A.5 | Heartbeat: `loop_hz` `work_ms` `sleep_ms` `cmd_q` | ✅ |
| A.6 | Lua: `lever_notch` + `last_cmd_id` | ✅ |
| A.7 | Parser probe: priorizar `lever_notch` | ✅ |
| A.8 | Tests `test_control_channel.py` | ✅ |
| A.9 | `loop_hz=20` alineado con Lua | ✅ |

---

## Fase B — IPC robusto (hecho)

| ID | Tarea | Estado |
| --- | --- | --- |
| B.1 | `adaptive_ack_timeout_s()` — 2–4 frames + p95 | ✅ |
| B.2 | ACK `path:value:ok:cmd_id` + correlación GetData | ✅ |
| B.3 | P1 sin fallback teclado (`ipc_only=True`) | ✅ |
| B.4 | Reintento en cola (3×, sin penalizar canal) | ✅ |
| B.5 | (Opcional) socket/pipe en lugar de archivos | ⏸ no bloquea P1 ni Fase C |
| B.6 | HTTP fallback palanca | ❌ retirado a propósito (teclado si IPC fail) |
| B.7 | Write UE4SS Class 323 `SetCurrentOutputValue` | ✅ 2026-08-27 17:13 |
| B.8 | Canal: `ipc_ok` alto, `KEY≈0`, HUD = 1 paso IPC | ✅ 2026-08-27 19:23 (`ipc_ok=5/5`, `KEY=0`, ACK 13–37 ms) |
| B.8b | P1: plan coherente y palanca a costa en andén | ❌ palanca se queda en B1 (`notch=3`); ver Fase C |

---

## Fase C — Planner sincronizado con palanca (un paso)

El actuador **ya existe**. C no es “hacer que Lua mueva”: es planning + cuándo se apaga P1.

Cada IPC es **HUD ± 1**. El plan que pide B2 desde P2 necesita varios ciclos; `reached_notch` es “llegó al destino del *BrakeCommand*”, no el ACK del paso.

### Evidencia B.8 — `logs/autopilot_20260827_192303.log`

Four Oaks, Class 323, probe `20260828a`.

| Fuente | En el log | ¿Fiable? |
| --- | --- | --- |
| Estación `parada=Four Oaks@2591m` → `@101m` | HTTP + odometría Python | Sí — baja con `spd` |
| Plan STATION `p1d=715m` → `600m` | Misma estación | Sí |
| Cartel `next_lim=55@2495.8m` / `probe Δdist=+0` | DriverAid cm (Lua hold + Python sin odo de límites) | **No** — fijo ~2 min; heartbeat `dist=1.6 mi` |
| `gap=` | `estación − cartel` | Basura (−2 km) porque el cartel no avanza |

Secuencia palanca:

1. 19:24:09 — `SPEED_LIMIT` B2 con `p1d=2496m` (cartel congelado) → 4→3→2, luego `RELEASE` a 4 @55 mph (sí soltó).
2. 19:24:28 — `STATION` Four Oaks B1 → IPC `4→3`. HUD B1 correcto.
3. ~536 m … 210 m — `p1dbg=sin_plan_activo`, handle sigue en 3.
4. 19:25:09 — `P1 reset fsm=APPROACHING spd=10.0` → `p1on=N`. Causa: `_p1_should_run` corta P1 en APPROACHING si `spd≤10` salvo cartel **agrupado** con la estación; con límite a 2,5 km no hay cluster.
5. ~101 m — `parada` salta a Sutton `@2261m` (FSM consumió Four Oaks). RELEASE STATION exige plan vivo y `spd≤~2` → **nunca corre**. Neutro solo al cerrar (`reset_neutral`).

El “no vuelve a 0, se queda en 1” es **B1** (`notch=3`), no P1 de tracción. IPC no es el fallo.

### Tareas (orden de implementación)

Independientes: **C.3a** (metros de cartel) no suelta la palanca; **C.2** sí.

| ID | Tarea | Cómo | Por qué |
| --- | --- | --- | --- |
| C.3a | Cartel: odometría si probe plano | ✅ `dist` baja; `probe_raw` sigue 2495.8 m (`20260827_202354`) | Evita SPEED_LIMIT @2496 m fijo |
| C.2 | No matar P1 con freno puesto | ⚠ + keep P1 si ya activo y `spd≤12` en APPROACHING | Reset @9.9 con handle retrasado |
| C.2b | RELEASE al cortar P1 | ✅ STOPPED con freno → `RELEASE`; reset con `brake_active` → notch 4 | Andén palanca 0/3 |
| C.1 | Esperar HUD antes de cambiar fase | Un destino por IPC | Burst B2→B1→RELEASE |
| C.3b | No B2 al 55 a ~1 km | ✅ horizonte B1: `bd+(reacción)+(zona apply)` | 56 mph @1018 m |
| C.3c | GUI distancia de límite interpolada | ✅ `Próx. límite` sin `probe` 1.6 mi | Punto 2 |
| C.3d | No resync cartel al parar | ✅ `spd<0.5` no pisa odo con raw 2495 | Tras Four Oaks |
| C.5 | FSM STOPPED → DEPARTING | ✅ parado + andén FSM / next_stop saltado / `_we_stopped` &lt;150 m | Punto 3 |
| C.4 | Watchdog vs cola IPC | No saturar / no pisar APPLY | No saltó |

No meter freight ni sockets aquí. No reactivar UFunctions crashy. No PATCH palanca HTTP.

**Criterio PASS Fase C:** `ipc_ok` alto; `next_lim` interpolado en GUI (sin 1.6 mi probe); no B2 a 1 km por 1 mph; FSM STOPPED/DEPARTING y siguiente parada tras puertas; RELEASE a costa; sin `P1 reset` con palanca en freno.

### Evidencia `logs/autopilot_20260827_202354.log` (+ UE4SS `20260828a`)

Canal **PASS** (`ipc_ok=21/21`, `KEY=0`). Lua un HUD por IPC.

**1. Freno lejano al 55.** C.3a cuenta metros (`2492→1018 m`, gap ~140 m con Four Oaks). A las 20:24:59: `spd=56` `lim=60` `elim=55`, **P1 SPEED_LIMIT B2 `dist=1018m` `distStart=0`**. El probe HUD sigue 1.6 mi; el plan interpolado aplica B2 en cuanto se supera 55. RELEASE @55.4. No es IPC: es techo/contención pronto (**C.3b**).

**2. GUI sin distancia de límite útil.** El ciclo log sí tiene `next_lim=55@…m`. Heartbeat: `dist` baja, **`probe=1.6 mi` fijo**. `_format_limit_ahead` usa `format_distance_pair(planning, probe)` y el 1.6 mi tapa el valor. No hay 2º límite en GetData (`dist_limit2`).

**3. Tras parar / puertas / no acelera.** EMERGENCIA STATION → notch 0 → `P1 reset spd=9.9` → `p1on=N`. FSM **no** STOPPED/DEPARTING: `APPROACHING Four Oaks` con `parada=Sutton@2125m`. Al parar, cartel **resync 2495.8 m**. Tras puertas, tracción `lever=6` y P1 **SPEED_LIMIT B2 @2473 m** con **`elim=10`**. Sigue la parada actual y frena (C.5 + C.2b + C.3d).

---

---

## Fase D — Telemetría auxiliar (después de C)

No hace falta para dar por bueno el canal 323. Sirve a física / learner / logs.

| ID | Tarea | Estado |
| --- | --- | --- |
| D.1 | `brake_cyl_bar` fiable en probe (Class 323) | ⏸ |
| D.2 | `probe_raw` / `dist_limit` fiable (Lua hold vs DriverAid plano) | ⏸ tras C.3a: si el HUD del juego también queda en 1.6 mi, interpolar; no “arreglar” cm inventados |
| D.3 | Resumen de sesión al cerrar autopilot | ✅ |

---

## Validación canal (B.8) — hecho 2026-08-27 19:23

Canal **PASS**. Criterio P1 (B.8b) **FAIL** — seguir Fase C, no repetir B.8 de IPC.

---

## Validación con un solo log (B.8 / C)

1. TSW6 + probe `20260828a` (F7 ON). **`-HTTPAPI` no hace falta para palanca** (sí para DriverAid/estaciones si el planning lo usa).
2. Class 323, palanca conocida (p. ej. P2).
3. Autopilot 1–2 min con frenadas P1; TSW en primer plano (teclado solo si ACK fail).
4. Cerrar autopilot → `SESIÓN CANAL`.
5. `logs/autopilot_*.log`: `IPC  … notch n→n±1`, `KEY=0` o casi, `match=Y`.
6. Si algo raro: `UE4SS.log` líneas `SetCurrentOutputValue out step=` (un HUD, no salto 6→4).

### Arranque

```text
Log sesión: logs/autopilot_....log
Autopilot iniciado  tgt=20Hz  control=on  learn=on
Probe mod: lever_notch+last_cmd_id+last_ack_ok  getdata=...\GetData.txt  lever=6  ...
Canal IPC armado (async writer + TelemetryReader 20Hz)
```

### Heartbeat (~2 s)

```text
heartbeat loop_hz=19.8 work=8ms sleep=42ms tgt=20Hz
  cmd_q=0 id=42 cf=Y ack=18ms ret=0 err=— match=Y lever=3 hud=3
  spd=45.2 lim=60 age=35ms seq=1842 telem_poll=20Hz
```

### Resumen canal (~10 s)

```text
canal [PASS]  ipc_ok=12/12 (100%)  ack_p95=45ms  enq=12 ret=0 drop=0 err=—
  async=12 KEY=0 p1rej=0  ticks=400 work_max=38ms slow=0
  loop_hz=19.5-20.0  telem_poll=19.8Hz  mod=lever_notch+last_cmd_id+...
```

### Cierre de sesión

```text
═══ SESIÓN CANAL FIN SESIÓN [PASS/WARN/FAIL] ═══  log=logs/autopilot_....log
  bucle: ticks=1200  loop_hz=19.6-20.0  work_max=38ms  slow(>150ms)=0
  IPC: ok=67/67 (100%)  ack_p95=45ms  enqueued=67  retries=0  drops=0  ...
  mandos: async=67  sync=0  KEY=0  p1_rejected=0  cf_hb=95%  match_hb=60  mod=...
```

### Veredicto automático (`acceptance_verdict`)

| Resultado | Condición |
| --- | --- |
| **PASS** | Sin incidencias en criterios abajo |
| **WARN** | Incidencia menor (p. ej. ack 50–95 %, `ack_p95` &gt; 200 ms, `KEY` &gt; 0) |
| **FAIL** | `ack_ok` &lt; 50 %, mod Lua sin `lever_notch`/`last_cmd_id`, bucle lento |

Criterios evaluados: `work>150ms`, `loop_hz_min<18`, `telem_poll<15Hz`, `mod_lua_viejo`,
`ack_ok<95%`, `ack_p95>200ms`, `KEY>0`.

---

## Glosario de campos en log

| Campo | Significado |
| --- | --- |
| `loop_hz` | Frecuencia real del bucle (ticks/s en ventana 2 s) |
| `work_ms` | Tiempo de `tick()` sin sleep |
| `sleep_ms` | Sleep hasta próximo tick |
| `telem_poll` | Hz del `TelemetryReader` |
| `cmd_q` | Mandos en cola + inflight |
| `id` | Último `cmd_id` enviado |
| `cf` | `last_cmd_id` en GetData coincide con `id` enviado |
| `ack` | Último ACK IPC en hilo escritor (ms) |
| `ret` | Reintentos acumulados en sesión |
| `err` | Último error IPC (`ack_timeout`, etc.) |
| `match` | `lever_notch` == objetivo del último mando |
| `lever` / `hud` | Muesca palanca real vs HUD Power |
| `P` / `fill` / `lrn` | Presión cilindro, fill-time learner (si hay datos) |
| `dist` / `probe` / `frozen` / `stale` | Planning interpolado vs cm probe; `frozen` = juego pausado; `stale=Y` = cartel plano + odo C.3a |
| `canal [PASS]` | Resumen cada 10 s |
| `SESIÓN CANAL` | Resumen al cerrar — **suficiente para validar Fase A/B** |
| `IPC ok id=N` | Línea por mando con ACK correcto |
| `IPC async id=N … falló` | Línea por mando sin ACK tras reintentos |
| `HTTP fallback OK` | IPC Lua falló; PATCH `InputValue` en Python tuvo éxito |
| `HTTP mandos falló` | Ni IPC ni HTTP movieron el mando |
| `http_ok` / `http_fb` | (propuesto) contador en `SESIÓN CANAL` cuando se exponga en métricas |

---

## Datos faltantes (pendiente de fases C/D)

Lo que **aún no** está disponible, no es fiable, o no se registra en el log de canal.

### Telemetría GetData — ausente o poco fiable

| Campo | Estado | Impacto |
| --- | --- | --- |
| `brake_cyl_bar` | En mod Lua; a menudo `—` en Class 323 | Learner fill-time, `P=` en heartbeat, filtro “esperando aire” |
| `last_ack_ok` | Solo en línea `Probe mod:` al arranque | No se repite en heartbeat; diagnóstico ACK Lua vs Python |
| `handle_notch` | HUD Power derivado | Obsoleto para control; usar `lever_notch` |
| `probe_dist_limit_m` / `probe_raw` | Puede quedar **fijo** con `frozen=N` (sesión 19:23: 2495.8 m) | C.3a — no usar solo `frozen=` |
| `distance_next_m` (HTTP) | Poll lento (~1 Hz) | `dist` en heartbeat puede ir retrasado respecto al juego |

### Métricas IPC — no expuestas en resumen canal

| Dato | Estado | Notas |
| --- | --- | --- |
| `telem_ms` | No logueado | Tiempo hasta `lever_notch` == objetivo (solo `ack_ms`) |
| `roundtrip_ms` | No logueado | ACK + confirmación en GetData en un solo número |
| `telem_cmd_id` vs `id` | Parcial (`cf=Y/N`) | No se imprime `telem_cmd_id` numérico en heartbeat |
| Latencia por mando (CSV) | Eliminado | Antes `control_latency_probe.py`; ver líneas `IPC ok` / `IPC async` |
| `ack_timeout_s` adaptativo | Interno en `CommandState` | No visible en log salvo que infieras por `ack_timeout` |

### Lógica de control — no sincronizada (Fase C)

| Dato / comportamiento | Estado |
| --- | --- |
| `reached_notch` bloquea FSM P1 | No — planner puede avanzar sin esperar palanca |
| RELEASE STATION | Solo si plan vivo y `spd≤~2`; P1 muere antes (`_p1_should_run`) |
| `_p1_should_run` @ APPROACHING ≤10 mph | ~~Corta P1 salvo cluster~~ C.2: si `brake_active` P1 sigue |
| Ventanas `sin_plan_activo` | Siguen con cartel plano / plan caído |
| Watchdog vs cola IPC saturada | Sin coordinación explícita |

### Qué añadir cuando toque cada fase

| Fase | Log / dato nuevo propuesto |
| --- | --- |
| C.1 | `p1_wait=notch` / `p1_timeout` en cycle o heartbeat |
| C.2 | `p1on` sigue Y con `notch<4`; log `P1 RELEASE` al reset; no `P1 reset` @10 mph en freno |
| C.3a | `next_lim` baja o `probe_stale=Y` + dist interpolada; `gap` no −2000 m con estación a 600 m |
| D.1 | `brake_cyl_bar` en heartbeat y flag `mod` sin `falta=brake_cyl_bar` |
| D.2 | Tras C.3a: deprecar `probe=` o `probe_src=held/odo` |
| B.5 | No priorizar; archivos bastan a 20 Hz |

---

## Orden de trabajo

1. ~~**Fase A**~~ — hecho  
2. ~~**Fase B**~~ — hecho  
3. ~~**B.7 Class 323**~~ — `test-ipc` PASS  
4. ~~**B.8 canal**~~ — `SESIÓN CANAL` PASS (`autopilot_20260827_192303.log`)  
5. **Fase C** — ~~C.3a~~ C.2/C.2b/C.3b/c/d/C.5 en código; **siguiente C.1** (esperar HUD) + validar con log Four Oaks  
6. **Fase D** — `brake_cyl`; D.2 solo si C.3a no basta (DriverAid muerto)  
7. **B.5 sockets** — solo si el disco del puente se queda corto  
8. Otros trenes — `Notches` + escala Output propios

---

## Comandos útiles

```bat
install_ue4ss_probe.bat
iniciar_monitor.bat
  test-brake    rem prueba PATCH HTTP (DriverInput)
  test-ipc      rem prueba SendCommand → Lua → UE (sin HTTP)
python -m pytest tests/test_control_channel.py tests/test_channel_diagnostics.py tests/test_handle_controller.py tests/test_tsw_ipc_bus.py -q
```
