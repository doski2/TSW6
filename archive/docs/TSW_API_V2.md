# TSW6 — API directa V2 (solo frenos)

Plan para mandar **frenos** al juego sin RailBridge, usando la API HTTP oficial de TSW6.
Inspirado en el `command_bus` de [Dastsc](C:\Users\doski\Dastsc) (Train Simulator Classic).

**Estado:** 🟡 En curso — V2.0 y V2.1 implementados (tests sin juego).

---

## Objetivo

| Antes (archivado) | Ahora (activo) |
| ----------------- | -------------- |
| Telemetría + mandos vía **RailBridge** (`archive/railbridge/`) | **Lectura** `tsw_telemetry_source.py` + **escritura** `tsw_command_bus.py` |
| RPC companion | `PATCH /set/{ruta}.Value` → juego directo |
| Dependencia RailBridge + CMP | Solo TSW6 con `-HTTPAPI` (futuro: mod UE4SS — ver `INVESTIGACION.md`) |

**RailBridge está archivado** (2026-06-13). El stack activo es:

- **Lectura:** `tsw_telemetry_source.TswTelemetrySource` — polling HUD vía HTTPAPI.
- **Lectura rápida (bajo nivel):** `tsw_fast_telemetry.FastControlReader`.
- **Escritura (frenos / handle combinado):** `tsw_command_bus.py`.
- **Diagnóstico humano:** `tsw_monitor.py`, `diag_controles.bat` (lanza el monitor).

Alcance inicial V2: **frenos** (+ handle combinado UK). Tracción libre, reverser y emergencia bloqueados.

---

## Límites de latencia (HTTPAPI)

La API HTTP de TSW (`-HTTPAPI`, puerto `31270`) **no es tiempo real**. Es **request/response**:
cada lectura o mando es una petición HTTP independiente. Es la fuente **actual** del autopiloto
hasta que exista el mod UE4SS (ver `INVESTIGACION.md`).

### Mediciones en sesión real (Class 323, PC local)

| Operación | Latencia observada | Notas |
| --------- | ------------------ | ----- |
| Primera petición de una ráfaga | ~**2 s** | Penalización intermitente de la API |
| Cada `GET /get/...` siguiente (misma sesión) | ~**15 ms** | Solo en serie, no en paralelo |
| 4 lecturas HUD (speed + mando + freno + acel.) | ~**80 ms** | `FastControlReader` optimizado → ~12 Hz máx |
| `PATCH /set` (escribir freno) | ~**50–150 ms** | Una orden por petición |
| Suscripción `/subscription` | Variable / a menudo vacía | Conocido como poco fiable en foros Dovetail |

### Ciclo cerrado leer → decidir → mandar (solo HTTP)

En el mejor caso, un ciclo completo por API sería:

```text
  leer telemetría (~80 ms)  +  decidir  +  PATCH freno (~100 ms)  ≈  180–300 ms por ciclo
  → 3–5 decisiones por segundo como techo práctico
```

A **80 km/h** el tren avanza **~4–7 m** entre ciclos. Eso **no es preciso** para reaccionar a un límite
de velocidad, una señal o una pendiente pronunciada.

### Comparación histórica (RailBridge archivado)

| | RailBridge (archivado) | API HTTP TSW (activo) |
| --- | --- | --- |
| Modelo | Push SSE | Poll HTTP |
| Latencia lectura | ~50–200 ms | ~80 ms+ por ciclo |
| Datos | Velocidad, límite, gradiente, planning… | HUD básico (speed, mando, freno) |
| Estado | `archive/railbridge/` | `tsw_telemetry_source.py` |

### Qué usar para qué

| Uso | Fuente | ¿Apto? |
| --- | --- | --- |
| Autopiloto / aprender (hoy) | `tsw_telemetry_source.py` | ✅ con limitaciones |
| Mandar freno / handle | `tsw_command_bus.py` | ✅ |
| Monitor humano | `tsw_monitor.py` | ✅ |
| Autopiloto preciso (futuro) | Mod UE4SS | 🟡 planificado |

### Arquitectura actual

```text
  ┌─────────────┐   GET /get HUD_*    ┌──────────────────────┐
  │   TSW6      │ ──────────────────► │ tsw_telemetry_source │  ← lectura
  │  (-HTTPAPI) │                     └──────────┬───────────┘
  └──────┬──────┘                                │
         │ PATCH /set                            ▼
         │                              ┌──────────────────┐
         └────────────────────────────► │ speed_decider +  │
                                        │ handle_controller│
                                        └────────┬─────────┘
                                                 │
                                                 ▼
                                        ┌──────────────────┐
                                        │ tsw_command_bus  │  ← escritura
                                        └──────────────────┘
```

El monitor (`iniciar_monitor.bat`) **no participa** en el autopiloto: es diagnóstico humano.

### Medir en tu PC

Con TSW en cabina y `-HTTPAPI` activo:

```bat
python -c "from tsw_fast_telemetry import reader_from_key_file, benchmark; r=reader_from_key_file(); print(benchmark(r))"
```

Salida esperada (orden de magnitud): `avg_ms` ~80, `hz` ~10–12, `source` `poll` o `subscription`.

### Conclusión

`-HTTPAPI` es la base **actual** (lectura + escritura). Para frenado fino a alta frecuencia,
el plan es **mod UE4SS** (`INVESTIGACION.md`). RailBridge quedó en `archive/railbridge/`.

---

## Referencias externas

- [Dovetail — Train Sim World API

  Support](https://forums.dovetailgames.com/threads/train-sim-world-api-support.94488/) — PDF *TSW
  External Interface API 1.5*

- API base: `http://localhost:31270`
- Auth: header `DTGCommKey` (y `X-API-Key` por compatibilidad) con clave en `Documents\My

  Games\TrainSimWorld6\Saved\Config\CommAPIKey.txt`

- Arranque: `-HTTPAPI` en opciones de Steam

Operaciones útiles:

| Método                              | Uso                                          |
| ----------------------------------- | -------------------------------------------- |
| `GET /list`                         | Descubrir rutas de mandos del tren en cabina |
| `GET /get/{ruta}.Value`             | Leer posición actual                         |
| `PATCH /set/{ruta}.Value?Value={n}` | Fijar mando (absoluto)                       |

---

## Patrón copiado de Dastsc

| Dastsc (TSC)                              | TSW6 V2                                         |
| ----------------------------------------- | ----------------------------------------------- |
| `command_bus.py` → `SendCommand.txt`      | `tsw_command_bus.py` → `PATCH` API              |
| `_ALLOWED_CONTROLS` / `_BLOCKED_CONTROLS` | Igual — allowlist de rutas TSW                  |
| `dispatch_command()` → `{ok, error}`      | `dispatch_brake(path, value)`                   |
| Perfil `mappings.brake`                   | `control_schemas` + campo `tsw_api_paths`       |
| Class 323: `ThrottleAndBrake:-0.5`        | `PowerBrakeHandle` valor 0–1 (negativo = freno) |
| Rate limit 2 s en AUTO                    | Mismo en integración autopiloto                 |

**No se copia:** plugin Lua, RailDriver, WebSocket Nexus, UI V4.

---

## Arquitectura prevista

```text
```

---

## Mandos permitidos (V2 — solo freno)

### Layout `combined` (UK — Class 323)

| Acción lógica   | Ruta API esperada                          | Valor                       |
| --------------- | ------------------------------------------ | --------------------------- |
| Freno B1–B4     | `PowerBrakeHandle` (confirmar con `/list`) | 0.0 = neutro, ↓ = más freno |
| Liberar         | misma ruta                                 | 0.5 (neutro) o según perfil |

### Layout `freight_na` (SD40-2 — fase posterior)

| Eje                 | Endpoint TSW (tsw-en)    | Prioridad V2        |
| ------------------- | ------------------------ | ------------------- |
| Freno automático    | `AutomaticBrake`         | Fase V2b            |
| Freno independiente | `IndependentBrake`       | Fase V2c            |
| Freno dinámico      | `DynamicBrake`           | Fuera de V2 inicial |

### Bloqueados siempre

- `EmergencyBrake` / freno de emergencia
- `Reverser`, `MasterKey`
- Cualquier ruta no listada en allowlist ni en `tsw_api_paths` del tren

---

## Fases de implementación

| Fase     | Descripción            | Entregables                                                                        | Estado   |
| -------- | ---------------------- | ---------------------------------------------------------------------------------- | -------- |
| **V2.0** | Cliente HTTP           | `tsw_api_client.py`, tests unitarios (mock HTTP)                                   | ✅       |
| **V2.1** | Command bus frenos     | `tsw_command_bus.py` — allowlist, clamp, `dispatch_brake`                          | ✅       |
| **V2.2** | Descubrir mandos       | `descubrir_mandos.py` + `descubrir_mandos.bat` → guarda rutas en `control_schemas` | ⬜       |
| **V2.3** | Prueba manual UK       | `probar_freno.bat` — B1/OFF en Class 323 sin RailBridge                            | ⬜       |
| **V2.4** | Integración autopiloto | `handle_controller` rama `tsw_api`; `TswConnection.mode == "tsw_api"`              | ⬜       |
| **V2.5** | Freight freno auto     | `AutomaticBrake` en SD40-2                                                         | ⬜       |
| **V2.6** | Freight ind / dyn      | `IndependentBrake`, `DynamicBrake`                                                 | ⬜       |

### Criterios de aceptación por fase

**V2.3:** En cabina Class 323, `probar_freno.bat` aplica freno servicio y libera sin RailBridge
abierto.

**V2.4:** `iniciar_autopilot.bat` con flag `--tsw-api` frena vía API directa; telemetría puede
seguir en companion.

**V2.5:** SD40-2 frena con `AutomaticBrake` al menos en prueba manual.

---

## Archivos nuevos (previstos)

| Archivo                   | Rol                                          |
| ------------------------- | -------------------------------------------- |
| `tsw_api_client.py`       | Cliente HTTP GET/PATCH + key                 |
| `tsw_command_bus.py`      | Validación y envío de frenos (estilo Dastsc) |
| `tsw_fast_telemetry.py`   | Lectura HUD optimizada + benchmark           |
| `tsw_monitor.py`          | Monitor consola (solo diagnóstico humano)    |
| `descubrir_mandos.py`     | `GET /list` → actualiza `control_schemas`    |
| `probar_freno.py`         | CLI interactiva de prueba                    |
| `descubrir_mandos.bat`    | Lanzador descubrimiento                      |
| `probar_freno.bat`        | Lanzador prueba freno                        |
| `test_tsw_api_client.py`  | Tests cliente                                |
| `test_tsw_command_bus.py` | Tests command bus                            |

### Extensión de `control_schemas`

```json
```

---

## Fuera de alcance V2 (inicial)

- Tracción (`Throttle`, subir handle)
- Telemetría completa sin RailBridge (gradiente, route monitor, planning)
- `BrakeSelector` inteligente (Fase 4 freight NA plan)
- UI web / Nexus
- Consola Xbox (API solo PC)

---

## Riesgos y mitigaciones

| Riesgo                          | Mitigación                                           |
| ------------------------------- | ---------------------------------------------------- |
| Rutas API distintas por tren    | `descubrir_mandos` + guardar en schema por vehículo  |
| Conflicto con teclado/jugador   | Rate limit; solo enviar cuando autopiloto activo     |
| Menos telemetría que RailBridge | V2.4: lectura companion + escritura API (híbrido)    |
| Nombres con espacios en `/list` | URL-encode (`%20`) según foros Dovetail              |
| Key inválida tras reinicio TSW  | Recargar `CommAPIKey.txt` (ya hace `tsw_monitor.py`) |

---

## Relación con FREIGHT_NA_PLAN

| Plan freight                       | V2 API                                               |
| ---------------------------------- | ---------------------------------------------------- |
| Fase 4 `brake_selector.py`         | Decisor **qué** freno — independiente del transporte |
| Fase 5 `handle_controller` freight | V2 aporta **cómo** enviar sin RailBridge             |
| Fase 0 `control_schemas`           | V2 añade `tsw_api_paths` al mismo JSON               |

Orden recomendado: **V2.0–V2.4** en paralelo con Fase 4 del plan freight (selector puede usar RPC o
API).

---

## Seguimiento

| Fecha      | Hito                                              |
| ---------- | ------------------------------------------------- |
| 2026-08-16 | Documento V2 creado                               |
| 2026-08-16 | V2.0 `tsw_api_client.py` + tests                  |
| 2026-08-16 | V2.1 `tsw_command_bus.py` + tests                 |
| 2026-08-16 | Sección latencia HTTPAPI + `tsw_fast_telemetry`   |
| —          | V2.2 descubrir mandos (requiere juego en cabina)  |
| —          | V2.3 prueba Class 323                             |
| —          | V2.4 autopiloto híbrido                           |

---

## Próximo paso de código

**V2.2:** `descubrir_mandos.py` + `.bat` — en cabina con Class 323, `GET /list` → `tsw_api_paths` en `control_schemas`.

**V2.3:** `probar_freno.bat` — prueba manual B2 / neutro sin RailBridge.
