# Guía de uso

## Requisitos

| Actividad | TSW6 | UE4SS probe | `-HTTPAPI` |
| --- | --- | --- | --- |
| Calibrar (`aprender.bat`) | ✅ | ✅ recomendado | No |
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
- **Escribe** frenos vía `SendCommand.txt` (IPC Lua; HTTP PATCH como fallback).
- **Planning límites:** probe UE4SS ~20 Hz (2 límites adelante).
- **Planning estaciones:** HTTP `DriverAid` + **`tsw_hud.db`** (horario comercial,

  `car_stop_signs`).

`-HTTPAPI` **no** es necesario para mandos ni distancias a límites. **Sí** hace falta para
paradas programadas con horario HUD (`currentServiceName` + `geoLocation`).

Clave API (planning HTTP): `Documents\My Games\TrainSimWorld6\Saved\Config\CommAPIKey.txt`.

Detalle IPC: [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md) · `tsw_ipc_bus.py`.
Horarios: [HUD_TIMETABLE.md](HUD_TIMETABLE.md).

---

## Horarios HUD (`tsw_hud.db`) — opcional

Para filtrar paradas del servicio activo (sin paso, dirección correcta, tablón `car_stop`):

1. `preparar_db_hud.bat` — BD semilla del mod oficial + sincronizar a `TSW6\tsw_hud.db`
2. `abrir_hud_extraccion.bat` — extraer DLCs en `hud.exe` → **Load my DLCs**
3. Tras cada extracción: volver a ejecutar `preparar_db_hud.bat`
4. `python verificar_hud_db.py` — comprobar BD y horario 2R17 / Cross-City
5. En juego: TSW con **`-HTTPAPI`**, servicio comercial → GUI **Planning** muestra `[horario HUD#…]`

Scripts auxiliares: `extraer_horario_hud.bat`, `instalar_rust_hud.bat`, `refrescar_path_rust.bat`.

---

## Lanzadores

| `.bat` | Función |
| --- | --- |
| `install_ue4ss_probe.bat` | Copia mod UE4SS al juego |
| `probe_ue4ss.bat` | Monitor telemetría probe |
| `probe_ue4ss_log.bat` | Igual + guarda `logs/ue4ss_probe_*.txt` |
| `diag_controles.bat` | Monitor API HTTP (alternativa) |
| `aprender.bat` | Calibración guiada |
| `iniciar_autopilot.bat` | Autopiloto con perfil calibrado |
| `iniciar_monitor.bat` | Monitor API (depuración) |
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

Usa el perfil existente. **No calibra** salvo `--learn` en línea de comandos.

| Opción | Modo |
| --- | --- |
| **1** | Sigue límite de vía |
| **2** | Velocidad máxima personalizada |
| **3** | Solo monitorizar (`--no-control`) |
| **4** | Telemetría manual por teclado |
| **5** | Monitor API |

**Requisitos:** perfil calibrado + **TelemetryProbeMod** activo.

- **Mandos:** IPC (sin `-HTTPAPI`).
- **Paradas HUD:** `-HTTPAPI` recomendado.
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
| `iniciar_autopilot` | Conduce con ese conocimiento (IPC mandos; HTTP para paradas HUD) |

Más detalle técnico: [ARQUITECTURA.md](ARQUITECTURA.md) ·
[HUD_TIMETABLE.md](HUD_TIMETABLE.md) ·
[PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md).
