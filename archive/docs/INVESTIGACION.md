# Investigación — TSW6 sin RailBridge (telemetría rápida + frenado estilo Dastsc)

**Fecha:** 2026-06-13  
**Estado:** 🟡 En discusión — este archivo es el lugar para comentar y decidir.

---

## Decisión de dirección

| Antes (V1) | Ahora (objetivo) |
| ---------- | ---------------- |
| Telemetría vía **RailBridge** companion (SSE, puerto 51160) | **No usar RailBridge** |
| Mandos vía RPC companion o teclas simuladas | Mandos directos al juego (API o mod in-process) |
| Autopiloto híbrido companion + HTTP | Bucle **lectura rápida + command bus** al estilo **Dastsc** |

**Resumen:** queremos datos **en directo y rápidos** para recopilar perfiles y montar un sistema de frenado/autopiloto similar al de Dastsc (Train Simulator Classic), **sin depender de RailBridge ni del companion**.

---

## Referencia: cómo funciona Dastsc

Dastsc (`C:\Users\doski\Dastsc`) usa un patrón **Lua in-process + IPC por archivos**:

```text
  ┌──────────────────┐     GetData.txt (1 línea/tick)     ┌─────────────────┐
  │  TSC + plugin    │ ───────────────────────────────────► │  Python backend │
  │  Lua (in-game)   │     velocidad, BC, freno, esfuerzo…  │  telemetry_reader│
  └──────────────────┘                                      └────────┬────────┘
         ▲                                                             │
         │     SendCommand.txt (Control:valor)                        │
         └─────────────────────────────────────────────────────────────┘
                              command_bus.py
```

| Pieza | Rol |
| ----- | --- |
| `GetData.txt` | Telemetría **push** cada tick (~20–60 Hz), latencia mínima |
| `SendCommand.txt` | Escritura de mandos con **allowlist** y clamp |
| `command_bus.py` | Valida, formatea y escribe; nunca manda emergencia sin policy |
| `telemetry_reader` | Lee línea a línea, parsea, alimenta governor / decider |

**Por qué funciona:** lectura y escritura ocurren **dentro del proceso del simulador** (Lua). Python solo consume un archivo o socket; no hay HTTP ni polling de red.

Docs útiles en Dastsc: `docs/GUIA_TECNICA_IPC.md`, `docs/COMPARATIVA_LUA_RAILDRIVER.md`, `backend/core/command_bus.py`.

---

## Qué hemos probado en TSW6 (HTTPAPI)

TSW6 expone la **Dovetail External Interface** (`-HTTPAPI`, `localhost:31270`).

### Lo que sí sirve

| Uso | Módulo | ¿Apto? |
| --- | ------ | ------ |
| Diagnóstico humano (consola) | `tsw_monitor.py` | ✅ |
| Descubrir endpoints / esquemas | `tsw_api_client.py` `discover` | ✅ |
| **Escritura de frenos** (una orden) | `tsw_command_bus.py` | ✅ con reservas |
| Tests sin juego | `test_tsw_api_client.py`, etc. | ✅ |

### Lo que NO sirve para el bucle de control

| Problema | Medición (Class 323, PC local) |
| -------- | ------------------------------ |
| Primera petición de cada ráfaga | ~**2 s** de penalización |
| Cada `GET` siguiente (misma sesión, en serie) | ~**15 ms** |
| 4 lecturas HUD (speed + power + brake + accel) | ~**80 ms** → techo ~12 Hz |
| Ciclo leer → decidir → `PATCH` freno | ~**180–300 ms** → 3–5 Hz |
| A 80 km/h | **4–7 m** entre decisiones → inaceptable para frenado fino |
| Suscripciones `/subscription` | A menudo vacías / poco fiables |

**Conclusión:** HTTPAPI es **request/response**. No sustituye un stream de telemetría. Para un autopiloto estilo Dastsc, **la lectura no puede ser solo HTTP**.

Detalle ampliado en `TSW_API_V2.md` (sección latencia). La lectura **interina** es HTTPAPI;
el objetivo final sigue siendo **mod UE4SS**.

---

## Vía prometedora: UE4SS + mod puente (estilo GetData)

En la carpeta de investigación del escritorio hay un paquete **DynamicHUD v1.0.0** (UE4SS):

`C:\Users\doski\Desktop\investigacion tsw 6\DynamicHUD v1.0.0`

### Qué hace DynamicHUD (y qué NO hace)

- **Sí:** hook en `ReceiveTick`, lee en Lua **sin red**:
  - `drivableActor:HUD_GetSpeed(result)`
  - `playerController:GetDriverAidData(driverAid)` → límite de velocidad
  - `playerController:GetDrivableActor()`
- **No:** no exporta telemetría a Python; solo cambia visibilidad del HUD (minimal/off según velocidad/objetivo).

Es **prueba de concepto** de que las mismas funciones que expone HTTPAPI se pueden llamar **in-process** cada tick.

### Arquitectura propuesta (V3 — sin RailBridge)

```text
  ┌─────────────────────────────────────────────────────────────┐
  │  TSW6 + UE4SS                                               │
  │  ┌─────────────────────┐                                    │
  │  │ TelemetryBridgeMod  │  cada tick (ReceiveTick):          │
  │  │  (Lua, nuevo)       │  HUD_GetSpeed, HUD_Get*Brake*,     │
  │  │                     │  GetDriverAidData, aceleración…    │
  │  └──────────┬──────────┘                                    │
  │             │ escribe                                         │
  │             ▼                                                 │
  │     GetData.tsv / named pipe / UDP loopback                  │
  └─────────────┬───────────────────────────────────────────────┘
                │
                ▼
  ┌─────────────────────────────┐       ┌──────────────────────┐
  │  tsw_telemetry_reader.py  │──────►│  governor / decider  │
  │  (parse línea, como Dastsc)│       │  freight_learner…    │
  └─────────────────────────────┘       └──────────┬───────────┘
                                                    │
                    ┌───────────────────────────────┴────────────────┐
                    ▼                                                ▼
         tsw_command_bus.py (HTTP PATCH)              SendCommand en Lua
         ya implementado, ~50–150 ms/orden            (futuro, más rápido)
```

| Canal lectura       | Canal escritura        | Notas                   |
| ------------------- | ---------------------- | ----------------------- | ------------------------------------------ |
| **A (recomendado)** | Mod Lua → archivo/pipe | `tsw_command_bus` HTTP  | Mínimo viable; reutiliza V2                |
| **B (óptimo)**      | Mod Lua                | Mod Lua ← `SendCommand` | Máxima paridad con Dastsc; todo in-process |

---

## Datos a exportar (borrador — comentar aquí)

Prioridad para **frenado NA** (SD40-2, layout `freight_na`):

| Campo | Fuente Lua / HUD | Uso |
| ----- | ---------------- | --- |
| `speed_ms` | `HUD_GetSpeed` | Governor, bandas de velocidad |
| `accel_ms2` | `HUD_GetAcceleration` | Validar aprendizaje |
| `max_speed_ms` | `HUD_GetMaxPermittedSpeed` | Límite activo |
| `power` | `HUD_GetPowerHandle` | Tracción / notch |
| `train_brake` | `HUD_GetTrainBrakeHandle` | Freno automático |
| `loco_brake` | `HUD_GetLocomotiveBrakeHandle` | Freno independiente |
| `dyn_brake` | `HUD_GetElectricBrakeHandle` | Freno dinámico |
| `gradient` | ¿DriverAid / formation? | Pendiente — **por confirmar in-game** |
| `vehicle_class` | `ObjectClass` del actor | Perfil JSON |

Formato sugerido (una línea, tab-separated, como Dastsc):

```text
speed_ms:12.34\tpower:0.375\ttrain_brake:0.0\tloco_brake:0.0\tdyn_brake:0.0\taccel_ms2:-0.12\tmax_speed_ms:22.22\tclass:BNSF_SD40_2_C
```

> **Comentario abierto:** ¿JSON por línea en vez de TSV? ¿Frecuencia fija 20 Hz o solo si cambió algo?

---

## Comparativa de tres enfoques

| | RailBridge companion | HTTPAPI solo | UE4SS TelemetryBridge |
| --- | --- | --- | --- |
| Dependencia externa | RailBridge + perfil YAML | Solo `-HTTPAPI` | UE4SS instalado |
| Latencia lectura | ~50–200 ms push | ~80 ms+ por ciclo poll | **~1 tick (~16–33 ms)** |
| Gradiente / planning | Sí (companion) | Limitado vía HUD | Por mapear en Lua |
| Escritura mandos | RPC companion | `PATCH /set` ✅ | Lua o HTTP |
| Estabilidad updates TSW | Media | Alta (API oficial) | **Riesgo:** hooks UE4SS |
| Alineado con Dastsc | No | Parcial (solo write) | **Sí** |

**Decisión actual:** descartar columna RailBridge; avanzar columna UE4SS + HTTP write (fase 1).

---

## Código existente en TSW6 (reutilizable)

| Archivo | Rol con nueva arquitectura |
| ------- | -------------------------- |
| `tsw_api_client.py` | Escritura + diagnóstico HTTP |
| `tsw_command_bus.py` | **Command bus frenos** (paridad Dastsc) |
| `tsw_fast_telemetry.py` | Prototipo HTTP; sustituido por reader del mod |
| `tsw_monitor.py` | Monitor visual; sigue útil sin RailBridge |
| `archive/railbridge/tsw_connection.py` | **Archivado** — companion SSE (no usar) |
| `tsw_telemetry_source.py` | **Activo** — lectura HTTPAPI |
| `governor_physics.py`, `speed_decider.py` | Sin cambio si el reader expone el mismo dict |
| `freight_learner.py`, `FREIGHT_NA_PLAN.md` | Perfiles multi-eje; fases 4–6 pendientes |

---

## Fases propuestas

### Fase 0 — Documentación y acuerdo ✅ (este archivo)

- [x] Decisión: sin RailBridge
- [x] Comparativa HTTP vs UE4SS vs Dastsc
- [ ] Comentarios del usuario sobre campos y formato

### Fase 1 — TelemetryBridgeMod (MVP)

- [ ] Copiar esqueleto de `DynamicHUDMod/Scripts/main.lua`
- [ ] Hook `ReceiveTick`; escribir `GetData.txt` en carpeta fija (ej. `%TEMP%\TSW6Bridge\`)
- [ ] Activar mod en `mods.txt`
- [ ] `tsw_telemetry_reader.py`: leer + parsear + benchmark Hz

### Fase 2 — Integración recolección / aprendizaje

- [ ] Adaptar `learn_monitor.py` / `control_diag.py` para fuente UE4SS
- [ ] Validar SD40-2: 4 ejes `freight_na` con latencia real

### Fase 3 — Bucle frenado (estilo Dastsc)

- [ ] `tsw_command_bus.dispatch_brake` desde `speed_decider`
- [ ] Opcional: `SendCommand` Lua para escritura más rápida
- [ ] `brake_selector.py` (Fase 4 de `FREIGHT_NA_PLAN.md`)

### Fase 4 — Producción

- [ ] Flag “mod activo” (evitar mandos huérfanos al salir, como Dastsc `NexusApplyCommands.flag`)
- [ ] Purga al arranque si quedó `SendCommand` / estado colgado

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
| ------ | ---------- |
| Update TSW rompe UE4SS / hooks | Fijar versión UE4SS; probar tras cada patch |
| Anticheat / EAC | UE4SS es mod local; usar solo offline / escenarios propios |
| I/O disco cada tick | Buffer en memoria + flush cada N ms; o named pipe |
| Mandos huérfanos al cerrar Python | Flag de “autopilot armed”; purga en Lua al `InitGameState` |
| HTTP write lento | Aceptable para pruebas; migrar a Lua write si hace falta |

---

## Material de referencia en el escritorio

| Ruta | Contenido |
| ---- | --------- |
| `investigacion tsw 6\DynamicHUD v1.0.0` | UE4SS + DynamicHUD (tick hook, HUD_Get*) |
| `investigacion tsw 6\tsw_projects-main\...\tsw_api_reader` | Mapa masivo endpoints HTTP (`CurrentDrivableActor_endpoints.json`) |
| `C:\Users\doski\Dastsc` | Patrón GetData / SendCommand / command_bus |

---

## Preguntas abiertas (comentar debajo o en issues)

1. **¿Formato IPC?** ¿TSV una línea (Dastsc), JSONL, o socket UDP?
2. **¿Solo frenos al principio** o también tracción vía command bus?
3. **¿Instalación UE4SS** en la carpeta del juego ya hecha o hay que documentar paso a paso?
4. **¿Gradiente y distancia a objetivo** son imprescindibles para v1 del autopiloto?
5. ~~**¿Mantener `tsw_connection.py`**~~ → **Archivado** en `archive/railbridge/` (2026-06-13).

---

## Historial

| Fecha | Nota |
| ----- | ---- |
| 2026-06-13 | Creación del documento; dirección sin RailBridge; UE4SS como lectura principal |
| 2026-06-13 | RailBridge archivado; `tsw_telemetry_source.py` sustituye companion |

---

## Notas / comentarios

<!-- Escribe aquí observaciones de sesiones en juego, decisiones, o enlaces a logs -->
