# Canal de control — contrato IPC v2

**Plan maestro:** [v2/PLAN_V2.md](v2/PLAN_V2.md) (§4.1 probe, §4.2 IPC, debate **D2**, § Orden paso
1).
**Histórico** (fases A–C, sesiones test-ipc 2026-08, crashes, debate rendimiento):
[archive/docs/CANAL_CONTROL_HISTORICO.md](../archive/docs/CANAL_CONTROL_HISTORICO.md).

**Última revisión:** 2026-09-01 — F-B masa **off** (3 vs 6 coches no cuadra HTTP); 9b-a adherencia
documentado; sin cablear.

---

## Resumen

| Capa | Rol v2 | Estado |
| --- | --- | --- |
| **Probe Lua** | Solo I/O: escribe `GetData.txt`, aplica `SendCommand.txt` | ✅ ~20 Hz Class 323 |
| **Puente ficheros** | `%TEMP%\TSW6Bridge\` | ✅ producción |
| **Python** | `TelemetryReader` + `AsyncCommandWriter` | ✅ |
| **HTTP** | Planning (estaciones, geo, masa) — **no** mandos, **no** límites P1 con F7 | ✅ |
| **SHM / sockets** | Sustituto del disco | ⏸ aplazado (ver abajo) |

Código: `mods/TelemetryProbeMod/Scripts/main.lua`, `tsw6/telemetry/tsw_ue4ss_reader.py`,
`tsw6/telemetry/control_channel.py`, `tsw6/telemetry/tsw_ipc_bus.py`.

---

## Lua probe ≠ HTTP API {#lua-probe--http-api}

El mod **no llama a HTTP**. El puente es la carpeta `%TEMP%\TSW6Bridge\`:

| Archivo | Quién escribe | Quién lee | Contenido | |
| --- | --- | --- | --- | --- |
| `GetData.txt` | **Lua** (~20 Hz) | **Python** | Telemetría — **overwrite** cada ciclo (`io.open` `"w"`) | |
| `SendCommand.txt` | **Python** | **Lua** | Una línea: `ControlName:cmd:cmd_id` (p. ej. `PowerBrakeHandle:0.3750:42`) | |
| `TSW6ApplyCommands.flag` | **Python** | **Lua** | Hay mandos armados | |
| `SendCommandAck.txt` | **Lua** | **Python** | `ControlName:cmd:ok\ | fail:cmd_id` |

Lua **no** escribe mandos en el puente: los **recibe**, aplica en UE (`SetCurrentOutputValue` en
323)
y devuelve ACK.

**Nombres de mando:** no se descubren en el tick; salen del paquete G-B / caché
([DRIVERINPUT_API.md](reference/DRIVERINPUT_API.md)). F9 = dump laboratorio.

---

## Contrato GetData v2 {#contrato-getdata-v2}

Formato: **una línea** `clave=valor` separada por espacios. Parser:
`parse_probe_line()` en `tsw_ue4ss_reader.py`. Valor `?` = desconocido (salvo `vehicle=?`).

**Debate D2:** este documento es la **fuente canónica** de claves. Añadir un campo = actualizar
**las cuatro** piezas en el mismo PR (regla atómica — [PLAN_V2 §
D2](v2/PLAN_V2.md#d2--schema-getdata)):

1. Tabla abajo (este doc)
2. `build_line()` / `extract_*` en `main.lua` (si el probe lo emite)
3. `ProbeSnapshot` + `parse_probe_line` en Python
4. Fixture pytest en `tests/` (D7)

### Campos en producción (probe escribe hoy)

| Clave | Tipo | Origen Lua | Uso Python |
| --- | --- | --- | --- |
| `seq` | int | contador tick | stale / freeze |
| `speed_ms` | float | HUD | P1, física |
| `power` | float | HUD | tracción |
| `power_neg` | 0/1 | HUD | tracción |
| `handle_notch` | int | HUD Power derivado | legacy; preferir `lever_notch` |
| `lever_notch` | int | palanca real | control, ACK match |
| `last_cmd_id` | int | último IPC aplicado | correlación cola |
| `last_ack_ok` | 0/1 | resultado último mando | diagnóstico |
| `train_brake` | float | cabina | freight / display |
| `loco_brake` | float | cabina | freight |
| `dyn_brake` | float | cabina | freight |
| `accel_ms2` | float | física | display |
| `brake_cyl_bar` | float | Simulation (323: `?`); candidato HUD gauge §2 | learner (fase D); ver [PLAN_V2 §2](v2/PLAN_V2.md) |
| `max_speed_ms` | float | HUD | display |
| `speed_limit_ms` | float | DriverAid escalar | límite **vigente** |
| `gradient_pct` | float | DriverAid | `physics.py` |
| `vehicle` | string | clase UE | paquete G-B |
| `dist_limit_cm` | float | 1.º cartel adelante | P1 `limit_brake` |
| `next_limit_ms` | float | mph del 1.º cartel | P1 `limit_brake` |
| `odo_m` | float | odómetro | C.3a, estaciones |
| `doors_telem` | 0/1 | telemetría | FSM (opcional) |
| `doors_dmi` | 0/1 | DMI | FSM puertas |
| `signal_red` | 0/1 | DriverAid `signalAspectClass==2` | P1 rojo (paso 5) |
| `signal_dist_cm` | float | DriverAid distancia señal (cm) | Con `signal_red=1` |
| `is_slipping` | 0/1 | `HUD_GetIsSlipping` | Log 9b-a; handler 9b-b pendiente |
| `traction_locked` | 0/1 | `HUD_GetIsTractionLocked` | Opcional con slip |

### Planning Python (no va en GetData)

Estado interno en `tsw_telemetry_source` — el probe **no** escribe estos campos en
`GetData.txt` (~20 Hz innecesario para masa).

| Campo | Canal | Plan |
| --- | --- | --- |
| `mass_kg` | HTTP `CurrentFormation/0/Simulation/ClampPowerInput.Mass` | Paso **9** F-B — poll arranque + 5 min |
| `mass_factor` | ~~`mass_kg / mass_ref`~~ **no usar en frenado** (F-B off; conteo 3 vs 6 coches no cuadra con HTTP) | `physics.py` — siempre 1.0 hasta nueva evidencia |
| `mass_ref_kg` | 1.ª lectura OK o semilla G-B | Evita doble conteo con learner |

Evidencia lab: `data/lab_exports/exports/20260830T213100Z/` (~45 550 kg). Detalle:
[PLAN_V2 §2 F-B](v2/PLAN_V2.md).

### Ejemplo de línea (323, recortada)

```text
```

### Qué **no** va en GetData (v2)

- Cola `nextSpeedLimits[]` completa (HTTP ~2 s; con F7 no alimenta P1)
- `nextSignals[]` / aspectos ámbar-verde (D8 fuera)
- Ritmo de frenado, cluster, reglas P1
- `pairs(driverAid)` en hot path del tick

---

## Contrato SendCommand / ACK {#contrato-ipc}

| Pieza | Regla |
| --- | --- |
| Formato mando | `NombreUE:valor_normalizado:cmd_id` — un mando por línea |
| Escala 323 | `cmd` 0..1 → muesca destino; Lua un paso HUD ±1 hacia destino |
| Actuador 323 | `SetCurrentOutputValue(muesca − 4)` — ver histórico B.7 |
| Cola Python | `AsyncCommandWriter` — reassert hasta ack (~120 ms adaptativo, 3 reintentos) |
| Mandos HTTP | **Fuera** producción 323; teclado A/D solo fallback fuera P1 si ACK fail |
| Agente v2 (`V2/tsw6v2/`) | **Mismo** puente; no segundo canal sin decisión |

**Criterio sesión:** `loop_hz` ≥ 18, `ipc_ok` ≥ 95 %, `KEY=0` en P1, `last_ack_ok=1` en marcha.
Detalle métricas y veredicto `SESIÓN CANAL`: [histórico § validación](
../archive/docs/CANAL_CONTROL_HISTORICO.md#validación-canal-b8--hecho-2026-08-27-1923).

---

## D2 — Cómo añadir un campo {#d2--añadir-campo}

Checklist **Fase 0** ([PLAN_V2](v2/PLAN_V2.md#fase-0--contrato-io)):

- [x] Claves canónicas documentadas (tablas arriba)
- [x] Huecos C1 documentados (`signal_red`, `signal_dist_cm`)
- [x] Hueco lim2 documentado (parser sí, Lua no)
- [x] Huecos §2 documentados (`is_slipping`, masa F-B HTTP — **F-B off** tras conteo vagones)
- [ ] **9b-a** probe emite `is_slipping` (+ opcional `traction_locked`)
- [ ] **9** poll masa HTTP (log opcional) — ~~`mass_factor` en `physics.py`~~ **descartado**
- [ ] Revisión: Lua sin ritmo/cluster en tick (auditoría periódica `main.lua`)

**Proceso por campo nuevo** (ej. `signal_red`):

```text
```

**Estado D2:** contrato **documentado**; cierre total cuando C1 esté cableado y checklist Fase 0
marcado en ejecución.

---

## Rendimiento y SHM {#rendimiento-y-shm}

Decisión 2026-08-28 (resumen; debate completo en
[histórico](../archive/docs/CANAL_CONTROL_HISTORICO.md#plan-debate--rendimiento--canal-v2-2026-08-28)):

| Opción | Decisión v2 |
| --- | --- |
| **A** — pulir tick Python, HTTP fuera del 20 Hz | ✅ hecho (Fase A) |
| **B** — SHM / pipe binario | ⏸ solo si el **disco** es cuello tras A |
| **C** — tick nativo Rust/C++ | ⏸ no ahora |
| **D** — TypeScript | ❌ descartado |

**Hechos:** probe Lua ~1 ms; hitch 2–3 s al **cargar** escenario = aceptado; objetivo **20 Hz
estables**, no 50 Hz. Lim2/señales/GPS andén no son “canal más rápido” — son**campos nuevos** (D2).

Si un día hay SHM: mismo layout de campos que `GetData.txt` (`v1` struct), no inventar claves en
paralelo.

---

## Odometría cartel (C.3a)

Si `dist_limit_cm` queda plano pero el tren avanza, Python resta con `v×dt` entre refrescos del
juego (`tsw_telemetry_source`). No es un campo GetData extra — es lógica planning.

Evidencia y Four Oaks: [histórico Fase
C](../archive/docs/CANAL_CONTROL_HISTORICO.md#fase-c--planner-sincronizado-con-palanca-un-paso).

---

## Diagnóstico rápido {#diagnostico}

| Síntoma | Causa probable |
| --- | --- |
| `seq` congelado | Bucle Python bloqueado o juego pausado/cerrado |
| `telem_poll` < `loop_hz` | Normal: Lua ~17–20 Hz, Python puede leer más |
| `ack_timeout` | Mod no cargado, timeout corto, o TSW sin foco |
| `last_ack_ok=0` | Lua no movió HUD — ver `UE4SS.log`, F9 |
| `dist_limit_cm` fijo @2495 m | Cartel DriverAid plano — C.3a activo si `odo` avanza |
| `cf=N` / `match=N` | ACK o palanca no coincide con último `cmd_id` |

**Glosario completo** (`loop_hz`, `work_ms`, `cmd_q`, …):
[histórico § glosario](../archive/docs/CANAL_CONTROL_HISTORICO.md#glosario-de-campos-en-log).

**Herramientas:**

```bat
```

Código métricas: `tsw6/telemetry/channel_diagnostics.py`.

---

## Class 323 — actuador (referencia)

| Dato | Valor |
| --- | --- |
| Objeto | `PowerBrakeHandle` (`IrregularLeverComponent`) |
| UFunction | `SetCurrentOutputValue` (eje −4…+4 = muesca − 4) |
| Build validado | `20260828a` — `test-ipc` PASS |
| Escala HUD | 0=B4 … 4=costa … 8=P4 — tabla completa en [histórico B.7](../archive/docs/CANAL_CONTROL_HISTORICO.md#class-323-uk--ipc-validado-2026-08-27-1713) |

---

## Orden de trabajo v2

| Prioridad | Tarea | Ref |
| --- | --- | --- |
| 1 | Mantener contrato GetData al día (este doc) | D2 |
| 2 | C1: `signal_red` + `signal_dist_cm` + fixture | PLAN_V2 §3, ejecución paso 4 |
| 2b | 9b-a: `is_slipping` en probe (solo log; sin handler) | PLAN_V2 §2, sesión `213100Z` |
| 2c | ~~9: masa F-B~~ log HTTP opcional; **sin** `mass_factor` | PLAN_V2 §2 — F-B off (3 coches / 45 550 kg vs 6 / 44 430 kg) |
| 3 | Producto `V2/tsw6v2/` mismo puente | D1, §4.7 |
| 4 | lim2 solo si tramo demuestra hueco | Fase 5 |
| 5 | SHM solo tras medición disco | Histórico debate B |

---

## Enlaces

| Documento | Contenido |
| --- | --- |
| [PLAN_V2.md §4.2](v2/PLAN_V2.md#42-ipc-archivo) | Semántica IPC en el plan producto |
| [PENDIENTE_DYNAMICHUD.md](v1/PENDIENTE_DYNAMICHUD.md) | Probe Lua, F7, foco desarrollo |
| [DRIVERINPUT_API.md](reference/DRIVERINPUT_API.md) | Catálogo mandos / perfiles |
| [FLUJO_FRENOS.md](v1/FLUJO_FRENOS.md) | P1 y prioridad objetivos |
| [ESTADO.md](v1/ESTADO.md) | Tablero global |
