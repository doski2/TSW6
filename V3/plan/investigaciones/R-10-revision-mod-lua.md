# R-10 — Revisión del mod Lua actual (V2)

- **Estado:** Hecha (revisión de documentación y código, sin juego) — 2026-11-13
- **Desbloquea:** [decisiones/0002](../decisiones/0002-empezar-por-el-mod-lua.md), PREGUNTAS § C.1, C.3, H
- **Visión resultante:** [documentacion/mod-lua.md](../documentacion/mod-lua.md)

## Pregunta

¿Qué se construyó en Lua para V2, qué funciona, qué se aprendió a base de fallos y qué no
sirve para una base que tiene que aguantar muchos trenes durante años?

## Método

Lectura de `docs/CANAL_CONTROL.md`, `docs/v2/PROBE_LUA.md`, `docs/v2/PLAN_API_EXPLORER.md`,
`docs/v2/PROBE_LOGS.md`, `docs/v2/INVESTIGAR.md`, `mods/ApiExplorerMod/README.md` y del código
de `mods/TelemetryProbeMod/Scripts/` y `mods/ApiExplorerMod/Scripts/`.

## Resultados

### Qué hay hoy (FACT)

| Pieza                 | Rol                                                      | Tamaño                         | Build       |
| --------------------- | -------------------------------------------------------- | ------------------------------ | ----------- |
| `TelemetryProbeMod`   | Producción: telemetría ~20 Hz + aplicar mandos (IPC)     | ~1 310 líneas, 6 módulos       | `20261006a` |
| `ApiExplorerMod`      | Laboratorio: capturas por tecla (F5–F7) a JSON           | ~2 520 líneas, 12 módulos      | `20260901a` |
| Puente Python         | `V2/tsw6v2/bridge/` (`getdata.py`, `ipc_bus.py`, …)      | —                              | —           |
| Paquetes de tren      | `data/vehicles/class_323.json`, `m3a_mnr.json`           | 2 trenes                       | —           |
| Exportaciones de lab  | `data/lab_exports/exports/`                              | 27 sesiones                    | —           |

**Transporte:** carpeta `%TEMP%\TSW6Bridge\`, con estos ficheros:

- `GetData.txt`: una línea `clave=valor` que se sobrescribe en cada ciclo, a unos 20 Hz.
- `SendCommand.txt`: una línea `Mando:valor:cmd_id`.
- `TSW6ApplyCommands.flag`: indica que hay mandos pendientes.
- `SendCommandAck.txt`: la respuesta `ok|fail` del mod.

El mod se engancha a `ReceiveTick` del `PlayerController` y cuesta alrededor de 1 ms por ciclo.

**Principio que ha funcionado:** «el probe observa, Python decide, el IPC ejecuta». El mod no
contiene reglas de conducción.

**Separar producción y laboratorio fue un acierto.** El probe de v1 era un `main.lua` de ~2 040
líneas que lo mezclaba todo. Al partirlo, el probe bajó a ~950 líneas y la exploración (F9, reflect,
volcados) pasó a un mod aparte.

**Regla atómica D2:** un campo nuevo exige cambiar en el mismo PR estas cuatro piezas:

1. La tabla de `CANAL_CONTROL.md`.
2. `build_line` en Lua.
3. `parse_probe_line` en Python.
4. Un fixture.

Funciona, pero es manual.

### Lecciones caras (FACT, salieron de fallos reales)

| Lección                                                                                          | Origen                         |
| ------------------------------------------------------------------------------------------------ | ------------------------------ |
| `BeginChangingVHID` en cada paso **bloquea el teclado** del jugador                              | builds `20260908a/b`, revertido |
| Introspección (`GetClass`, `ForEachProperty`, `GetFullName`) sobre objeto con `IsValid()==false` = **crash nativo** | explorer `20260830k` |
| `SetCurrentOutputValue` mueve el mando pero la **palanca 3D no se mueve** en cabina              | limitación conocida 323        |
| En 323 hay que mover **un peldaño por comando** (`SAFE_LEVER_WRITE`), no saltar                  | validación IPC 2026-08         |
| `Simulation.*` está **bloqueado desde Lua** en la 323; HTTP sí lo ve                             | L0.6d                          |
| Campos que en un tren valen siempre 0 (amperímetro, `TractiveEffort` en 323) y en otro no        | L0.6f, M3a                     |
| `signal_red` **desaparece** ~40 m antes en marcha (falta *latch*)                                | sesión `225433Z`               |
| `dist_limit_cm` se queda **plano** (p. ej. 2495 m) y hay que extrapolar con `v×dt` en Python     | C.3a                           |
| Hitch de 2–3 s al **cargar** escenario: aceptado                                                 | debate rendimiento 2026-08-28  |
| `pairs()` / `FindAllOf` en el ciclo caliente = coste y riesgo; se sacaron                        | auditoría probe v2             |
| Dos mods con el mismo `ReceiveTick` = doble hook / tirones                                       | PLAN_API_EXPLORER § Qué NO hacer |
| HTTP fuera del ciclo: el planning va por Python cada ~2 s, nunca en el tick                      | estrategia Lua vs HTTP         |

### Problemas para una base a largo plazo

1. **El tren está metido en el mod.** `config.lua` y `ipc.lua` contienen conocimiento de trenes
   concretos:
   - `PBH_INPUT_BY_NOTCH` es la tabla de la 323.
   - El actuador hace `SetCurrentOutputValue(muesca − 4)`.
   - `MC_VEHICLE_MARKERS = {"RVM_NYH","M7","M8","M9"}` sirve para reconocer los MC.
   - `SIGNAL_RED_ASPECT = 2` es UK.
   - Hay 16 nombres de puerta fijos en el código.

   Va contra el principio «el tren es un dato». Cada tren nuevo obliga a tocar Lua y a reinstalar
   el mod.
2. **Sin versión en el cable.** `PROBE_BUILD` solo se imprime en el log de UE4SS. La línea GetData
   no lleva versión de contrato ni de mod, así que Python no puede detectar un mod viejo o
   incompatible.
3. **Un solo mando por mensaje.** `SendCommand.txt` lleva una línea con un mando, y el actuador
   asume que todo es la palanca combinada (`PowerBrakeHandle` y sus alias). Freno independiente,
   dinámico separado, puertas, AWS… no tienen camino.
4. **Formato plano y vocabulario de la 323.** Hay `handle_notch`, `lever_notch`, `power_neg`. El
   valor `?` significa «desconocido» y además los campos opcionales aparecen o desaparecen según el
   tren. No hay forma de decir «este tren no tiene esto» frente a «no lo he podido leer».
5. **Sin marca de tiempo.** Solo hay `seq`. No se puede medir la latencia lectura → decisión →
   aplicado (investigación R-03).
6. **Código duplicado entre mods.** `util.lua` y `bridge.lua` existen en los dos. Los nombres de
   puerta se mantienen «en sync a mano» (comentario en `config.lua`).
7. **Sin tests de Lua.** Solo se prueba el lado Python (fixtures, `parse_probe_line`) y a mano en
   el juego (F8). `build_line` o el parseo de mandos nunca se ejecutan fuera del juego.
8. **El explorer no cumple su propio criterio.** El objetivo era menos de 1 500 líneas y ningún
   fichero de más de 300. Hoy tiene ~2 520, `formation.lua` llega a 628 y `controls.lua` a 366.
9. **Documentación repartida en 6+ documentos** con historial mezclado. El contrato vive en
   `CANAL_CONTROL.md`, pero el detalle por build está en `PROBE_LUA.md` y el lab en un documento de
   1 260 líneas.

### Lo que no sabemos (UNKNOWN)

- Si el transporte por ficheros aguanta más campos y más mandos sin pasar de ~1 ms (R-03).
- Qué versiones de UE4SS y de TSW6 rompen qué (R-06).
- Si `NetTractiveEffort` y la masa se pueden leer desde Lua en trenes distintos de la 323 (cola de
  `docs/v2/INVESTIGAR.md`).
- Cómo se ven los mandos de una loco con freno independiente o de una mercancías (R-05, aún sin lab).

## Conclusión

Hay que conservar tres cosas: el principio de que el mod solo hace I/O, la separación entre
producción y laboratorio, y la lista de lecciones caras, que se convierte en reglas del mod V3.

Para durar, el mod tiene que cambiar en cuatro cosas:

- No saber de trenes concretos (recibe la descripción desde el paquete).
- Hablar un contrato **versionado** con negociación inicial.
- Aceptar **varios ejes de mando**.
- Tener tests fuera del juego.

Propuesta completa en [documentacion/mod-lua.md](../documentacion/mod-lua.md).
