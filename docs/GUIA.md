# Guía de uso

## Requisitos

| Actividad | TSW6 | UE4SS probe | `-HTTPAPI` |
| --- | --- | --- | --- |
| Calibrar (`aprender.bat`) | ✅ | ✅ recomendado | No |
| Validar freno aire (`validar_freno.bat`) | ✅ | ✅ opcional | **Sí** (presión + effort) |
| Laboratorio frenos GUI | `validar_freno.bat` opción 1 | Probe + HTTP | CSV `logs/brake_physics/` |
| Monitor (`probe_ue4ss.bat`) | ✅ | ✅ | No |
| Autopiloto (`iniciar_autopilot.bat`) | ✅ | ✅ recomendado | **Sí** (mandos HTTP fallback + **estaciones/horario HUD**) |
| Horarios HUD (`preparar_db_hud.bat`) | ✅ | — | Recomendado (`PlayerInfo.geoLocation`) |
| Monitor API (`tsw_monitor.py`) | ✅ | — | Sí |

- **Python 3.9+** (3.11 recomendado; los `.bat` lo detectan).
- Desarrollo/tests: `requirements-dev.txt` + `.venv` (ver [docs/README.md](README.md)).
- Escenario cargado, **en cabina**, tren encendido.
- No se usa RailBridge. Código legacy: `archive/railbridge/`.

---

## UE4SS — TelemetryProbeMod

Telemetría rápida (~17 Hz) sin polling HTTP. Patrón Dastsc: archivo en
`%TEMP%\TSW6Bridge\GetData.txt`.

### Instalación (una vez)

1. Instalar paquete **DynamicHUD / UE4SS** en la carpeta del juego (ver

   [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md) A1).

2. Ejecutar **`install_ue4ss_probe.bat`** desde este repo (copia `mods/TelemetryProbeMod/`).
3. Editar `Mods\mods.txt` del juego:

   ```text
   ```

4. **Importante:** no debe existir `Mods\DynamicHUDMod\enabled.txt` (UE4SS lo carga aunque

   `mods.txt` diga `: 0`).

5. Reiniciar TSW6.

### En cabina

| Tecla | Acción |
| --- | --- |
| **F7** | Activar / desactivar probe |
| **F8** | Volcar línea a log + `GetData.txt` |

### Comprobar desde Python

```bat
```

Debe mostrar `seq` incrementándose y Hz ~15–20. Con `aprender.bat` verás modo **UE4SS** al conectar.

### Autopiloto (estado actual)

- **Lee** mandos y velocidad del probe (~20 Hz).
- **Escribe** mandos vía `SendCommand.txt` (**IPC Lua, preferido**; teclado A/D solo fallback;

  HTTP PATCH si no hay UE4SS).

- **Planning límites:** probe UE4SS ~20 Hz (2 límites adelante).
- **Planning estaciones:** HTTP `DriverAid` + **`tsw_hud.db`** (horario comercial,

  `car_stop_signs`).

- **Puertas:** telemetría física `PassengerDoor_*` (~20 Hz vía probe; HTTP como fallback).

  Mensajes DMI (`dmi-doors-open/closed`) son secundarios.

`-HTTPAPI` **no** es necesario para mandos ni distancias a límites. **Sí** hace falta para
paradas programadas con horario HUD (`currentServiceName` + `geoLocation`).

### Puertas de pasajeros

| Campo | Fuente | Uso |
| --- | --- | --- |
| `doors_telem` | Probe UE4SS o HTTPAPI `PassengerDoor_*` | Estado real (abierta/cerrada) |
| `doors_dmi` | Mensajes DMI en `GetDriverAidData` | Fallback / cruce con RailBridge |
| `doors_open` | Derivado en Python | GUI y FSM (prioriza `doors_telem`) |

**Probe** (`GetData.txt`): `doors_telem=1/0` lee `GetCurrentInputValue` en
`PassengerDoor_FL/FR` (y variantes por carro). Tras actualizar el mod, ejecutar
`install_ue4ss_probe.bat` y reiniciar TSW6.

**HTTPAPI** (si no hay probe): mismas rutas que el HUD oficial — p. ej.
`CurrentDrivableActor/PassengerDoor_FL.Function.GetCurrentInputValue`
(`ReturnValue > 0` → abierta).

La FSM de estación (`governor_station.py`) usa primero `doors_telem`; solo si falta
recurre a DMI u OCR.

Clave API (planning HTTP): `Documents\My Games\TrainSimWorld6\Saved\Config\CommAPIKey.txt`.

Detalle IPC: [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md) (sección «Mandos: IPC vs teclado»)
· `tsw_ipc_bus.py`.

**¿Por qué IPC?** Escribe el notch absoluto (0–8) en un ciclo. El teclado solo se usa si IPC
falla (5 intentos → penalización 5 min). No hace falta tener TSW en primer plano.
Horarios: [HUD_TIMETABLE.md](HUD_TIMETABLE.md).

---

## Horarios HUD (`tsw_hud.db`) — opcional

Para filtrar paradas del servicio activo (sin paso, dirección correcta, tablón `car_stop`):

1. `preparar_db_hud.bat` — BD semilla del mod oficial + sincronizar a `TSW6\tsw_hud.db`
2. `abrir_hud_extraccion.bat` — extraer DLCs en `hud.exe` → **Load my DLCs**
3. Tras cada extracción: volver a ejecutar `preparar_db_hud.bat`
4. `python verificar_hud_db.py` — comprobar BD y horario 2R17 / Cross-City
5. En juego: TSW con **`-HTTPAPI`**, servicio comercial → GUI **Planning** muestra `[horario

   HUD#…]`,
   columnas Llegada/Salida y próxima parada con arr/dep (validado 2026-08-24).

Scripts auxiliares: `extraer_horario_hud.bat`, `instalar_rust_hud.bat`, `refrescar_path_rust.bat`.

---

## Lanzadores

| `.bat` | Función |
| --- | --- |
| `install_ue4ss_probe.bat` | Copia mod UE4SS al juego |
| `probe_ue4ss.bat` | Monitor telemetría probe |
| `probe_ue4ss_log.bat` | Igual + guarda `logs/ue4ss_probe_*.txt` |
| `aprender.bat` | Calibración guiada |
| `iniciar_autopilot.bat` | Autopiloto con perfil calibrado (menú; opción 5 = monitor API) |
| `iniciar_monitor.bat` | Monitor API HTTP (`-HTTPAPI`) |
| `preparar_db_hud.bat` | BD semilla HUD + copia a TSW6 |
| `abrir_hud_extraccion.bat` | Abre `hud.exe` para extraer DLCs |
| `extraer_horario_hud.bat` | Setup completo extractor HUD (Rust) |

### Flujo recomendado (Class 323)

```text
```

- **UK** (Class 323…): `aprender.bat` opción **1**.
- **Freight NA** (SD40-2…): opción **2**; ver [FREIGHT_NA.md](FREIGHT_NA.md).

---

## `aprender.bat` — Calibración

Conduces manualmente; el monitor captura aceleración/frenado por muesca y banda de velocidad.

| Opción | Modo |
| --- | --- |
| **1** | Continuar — pasajeros UK (handle 0–8, mín. 5 mph) |
| **2** | Continuar — mercancías NA (4 mandos, mín. 2 mph) |
| **3** | Reset — pasajeros |
| **4** | Reset — mercancías |
| **5** | Salir |

Durante la sesión: **8 muestras** por celda; mantén un mando estable ~2 s; autoguardado cada 5 s.

**Salida:** `logs/profiles/<NombreTren>.json`

Con UE4SS no hace falta `-HTTPAPI` para calibrar. El gradiente de vía sale en el probe
(`gradient_pct` en `GetData.txt`); reinstala el mod con `install_ue4ss_probe.bat` si no lo ves.

---

## `iniciar_autopilot.bat`

Usa el perfil existente y **actualiza el JSON en vivo** (Auto-aprender activo por defecto).
Usa `--no-learn` en CLI o desmarca el checkbox en GUI para congelar el perfil.

| Opción | Modo |
| --- | --- |
| **1** | Sigue límite de vía |
| **2** | Velocidad máxima personalizada |
| **3** | Solo monitorizar (`--no-control`) |
| **4** | Telemetría manual por teclado |
| **5** | Monitor API |

En la GUI del autopiloto (pestaña **Aprendizaje**): **Auto-aprender** viene marcado por defecto;
desmárcalo si solo quieres refinar al frenar. Calibración guiada completa (opcional):
`aprender.bat`.

**Requisitos:** perfil calibrado + **TelemetryProbeMod** activo.

- **Mandos:** IPC (sin `-HTTPAPI`).
- **Paradas HUD:** `-HTTPAPI` recomendado.
- **Puertas:** probe UE4SS (reinstalar con `install_ue4ss_probe.bat` si no ves `doors_telem` en

  `GetData.txt`).

- **Aprendizaje:** pestaña **Aprendizaje** — *Auto-aprender* ON por defecto (todas las muescas).

  Desmarcar = solo muescas 0–3 al frenar.

- Opción **3** (`--no-control`): solo telemetría, sin escribir mandos.

---

## Dónde se guarda todo

```text
```

---

## Resumen

| Herramienta | Pregunta |
| --- | --- |
| `probe_ue4ss` | ¿El probe lee bien a ~20 Hz? |
| `aprender` | ¿Cuánto acelera/frena cada muesca? |
| `preparar_db_hud` | ¿Tengo horarios comerciales en `tsw_hud.db`? |
| `iniciar_autopilot` | Conduce con ese conocimiento (IPC mandos; HTTP para paradas HUD; probe para puertas) |

Más detalle técnico: [ARQUITECTURA.md](ARQUITECTURA.md) ·
[FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md) ·
[HUD_TIMETABLE.md](HUD_TIMETABLE.md) ·
[PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md).
