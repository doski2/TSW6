# Scripts `.bat` — mapa y conexiones

**Raíz repo:** `TSW6/` · **Juego (UE4SS):**
`C:\Program Files (x86)\Steam\steamapps\common\Train Sim World 6\WindowsNoEditor\TS2Prototype\Binaries\Win64\`

Los `.bat` de la **raíz** son accesos directos; la lógica está en `scripts/`.

## Flujo típico (probe + autopilot)

```text
1. install_ue4ss_probe.bat     → copia mods/TelemetryProbeMod/Scripts/* al juego
2. Arrancar TSW6               → UE4SS.log: Mod loaded 20260902b, probe ON
3. probe_ue4ss.bat             → lee %TEMP%\TSW6Bridge\GetData.txt
4. iniciar_autopilot.bat       → GUI Python (opción 1)
```

## Instalación UE4SS

| Raíz | Script real | Qué hace |
| --- | --- | --- |
| `install_ue4ss_probe.bat` | `scripts/ue4ss/install_ue4ss_probe.bat` | **xcopy** todo `Scripts/` → `Mods/TelemetryProbeMod/Scripts/` |
| `install_ue4ss_explorer.bat` | `scripts/ue4ss/install_ue4ss_explorer.bat` | Lab ApiExplorerMod (no con autopilot) |

**Tras cambiar Lua:** reinstalar probe y **reiniciar TSW** (UE4SS no recarga Lua en caliente).

## Telemetría probe (GetData)

| Raíz | Script real | Python |
| --- | --- | --- |
| `probe_ue4ss.bat` | `scripts/ue4ss/probe_ue4ss.bat` | `python -m tsw6.telemetry.tsw_ue4ss_reader` |
| `probe_ue4ss_log.bat` | `scripts/ue4ss/probe_ue4ss_log.bat` | Igual + `--log` → `logs/ue4ss_probe_*.txt` |

**Bridge IPC:** `%TEMP%\TSW6Bridge\` (`GetData.txt`, `SendCommand.txt`, …)

## Autopilot y monitor

| Raíz | Destino | Notas |
| --- | --- | --- |
| `iniciar_autopilot.bat` | `tsw_autopilot.py` | Menú GUI; `PYTHONPATH` = repo |
| `iniciar_monitor.bat` | `tsw_monitor.py` | HTTP `-HTTPAPI`; modos `test-ipc`, `monitor`, … |
| `aprender.bat` | `learn_monitor.py` | Calibración learner |
| `validar_freno.bat` | `tsw6.learning.brake_physics_monitor` | Lab frenos |

## Rendimiento / diagnóstico

| Raíz | Script real | Lee |
| --- | --- | --- |
| `lua_probe_perf.bat` | `scripts/ue4ss/lua_probe_perf.bat` | `UE4SS.log` (probe Hz) — ruta por defecto al juego |
| `autopilot_perf.bat` | `scripts/ue4ss/autopilot_perf.bat` | `logs/autopilot_*.log` |

## HUD / horario (Rust, opcional)

| Raíz | Script real |
| --- | --- |
| `preparar_db_hud.bat` | `scripts/hud/preparar_db_hud.bat` |
| `extraer_horario_hud.bat` | `scripts/hud/extraer_horario_hud.bat` |
| `abrir_hud_extraccion.bat` | `scripts/hud/abrir_hud_extraccion.bat` |
| `instalar_rust_hud.bat` | `scripts/hud/instalar_rust_hud.bat` |
| `refrescar_path_rust.bat` | `scripts/hud/refrescar_path_rust.bat` |

## mods.txt recomendado

**Autopilot / probe:**

```text
TelemetryProbeMod : 1
ApiExplorerMod : 0
```

**Solo lab:**

```text
TelemetryProbeMod : 0
ApiExplorerMod : 1
```

## Comprobar UE4SS.log

Buscar:

```text
[TelemetryProbe] Mod loaded 20260902b (v2 modules)
[TelemetryProbe] probe ON (F7 toggle)
[TelemetryProbe] seq=... speed_ms=...
```

Si falta `TelemetryProbeMod` → ejecutar `install_ue4ss_probe.bat`.

Ruta log:
`...\Train Sim World 6\WindowsNoEditor\TS2Prototype\Binaries\Win64\UE4SS.log`

## Teclas in-game (probe)

| Tecla | Acción |
| --- | --- |
| (auto) | Probe ON al cargar (`PROBE_AUTO_START`) |
| F7 | Apagar / encender probe |
| F8 | Volcar línea GetData al log (requiere estar en cabina) |
