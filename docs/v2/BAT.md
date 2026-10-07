# Scripts `.bat` — mapa y conexiones

**Raíz repo:** `TSW6/` · **Juego (UE4SS):**
`C:\Program Files (x86)\Steam\steamapps\common\Train Sim World 6\WindowsNoEditor\TS2Prototype\Binaries\Win64\`

Los `.bat` de la **raíz** son accesos directos; la lógica está en `scripts/` o `V2/`.

**¿Plan amps/puertas en campo?** → [CAMPO_SCRIPTS.md](CAMPO_SCRIPTS.md) — **`probe_ue4ss.bat`** (amps + `doors_telem`); Explorer opcional.

---

## Plan campo amps/puertas (resumen)

```text
Grabar amps + puertas     probe_ue4ss.bat  →  logs\probe\<stamp>\ue4ss_probe_*.txt
Informe amps (PC)         amp.bat
Explorer (solo excepción) explorar_tren.bat + F6
Instalar Lua              install_ue4ss_probe.bat  (explorer solo si lab)
```

---

## Instalación UE4SS

| Raíz                         | Script real                                | Qué hace                                                      |
| ---------------------------- | ------------------------------------------ | ------------------------------------------------------------- |
| `install_ue4ss_probe.bat`    | `scripts/ue4ss/install_ue4ss_probe.bat`    | **xcopy** → `Mods/TelemetryProbeMod/Scripts/`                 |
| `install_ue4ss_explorer.bat` | `scripts/ue4ss/install_ue4ss_explorer.bat` | Lab ApiExplorerMod                                              |
| `explorar_tren.bat`          | `python -m lab.vehicle_explorer`           | GUI Vehicle Lab — [VEHICLE_LAB.md](VEHICLE_LAB.md)            |
| `amp.bat`                    | `scripts/tools/amp.py`                     | Stats amps desde log probe                                      |
| `summarizar_amps_lab.bat`    | `scripts/tools/summarize_hud_amps.py`      | F5 opcional — `amps_report.md` en export lab                  |

**Tras cambiar Lua:** reinstalar el mod tocado y **reiniciar TSW** (UE4SS no recarga Lua en caliente).

## Telemetría probe (GetData)

| Raíz              | Script real                     | Python                                                                 |
| ----------------- | ------------------------------- | ---------------------------------------------------------------------- |
| `probe_ue4ss.bat` | `scripts/ue4ss/probe_ue4ss.bat` | `tsw_ue4ss_reader --log --simple` → `logs/probe/<stamp>/` + consola |

**Bridge IPC:** `%TEMP%\TSW6Bridge\` (`GetData.txt`, `SendCommand.txt`, …)

## Autopilot y monitor (no plan amps/puertas)

| Raíz                    | Destino                               | Notas                                           |
| ----------------------- | ------------------------------------- | ----------------------------------------------- |
| `iniciar_autopilot.bat` | `tsw_autopilot.py`                    | Menú GUI; `PYTHONPATH` = repo                   |
| `iniciar_monitor.bat`   | `tsw_monitor.py`                      | HTTP `-HTTPAPI`                                 |
| `aprender.bat`          | `learn_monitor.py`                    | Calibración learner                             |
| `validar_freno.bat`     | `tsw6.learning.brake_physics_monitor` | Lab frenos                                      |

## V2 producto

| Raíz / carpeta           | Notas                                      |
| ------------------------ | ------------------------------------------ |
| `V2\run_p1_session.bat`  | Sesión P1 / `trace` JSONL                  |
| `V2\run_gui.bat`         | GUI V2                                     |
| `V2\test_pytest.bat`     | Tests V2                                   |
| `tsw6_v2.bat`            | Atajo entorno V2                           |

## Rendimiento / diagnóstico

| Raíz                 | Script real                        | Lee                                                |
| -------------------- | ---------------------------------- | -------------------------------------------------- |
| `lua_probe_perf.bat` | `scripts/ue4ss/lua_probe_perf.bat` | `UE4SS.log` (probe Hz)                             |
| `autopilot_perf.bat` | `scripts/ue4ss/autopilot_perf.bat` | `logs/autopilot_*.log`                             |

## HUD / horario (Rust, opcional)

| Raíz                       | Script real                            |
| -------------------------- | -------------------------------------- |
| `preparar_db_hud.bat`      | `scripts/hud/preparar_db_hud.bat`      |
| `extraer_horario_hud.bat`  | `scripts/hud/extraer_horario_hud.bat`  |
| `abrir_hud_extraccion.bat` | `scripts/hud/abrir_hud_extraccion.bat` |
| `instalar_rust_hud.bat`    | `scripts/hud/instalar_rust_hud.bat`    |
| `refrescar_path_rust.bat`  | `scripts/hud/refrescar_path_rust.bat`  |

## Otros

| Raíz            | Uso breve        |
| --------------- | ---------------- |
| `run_git.bat`   | Git asistido     |
| `test_ipc_v2.bat` | IPC tests (raíz) |

## `mods.txt` recomendado

**Probe (fases 1, 2, 4):**

```text
TelemetryProbeMod : 1
ApiExplorerMod : 0
```

**Solo lab (fase 3, F5/F6):**

```text
TelemetryProbeMod : 0
ApiExplorerMod : 1
```

## Comprobar UE4SS.log

Buscar línea de carga del mod activo y build **`20261006a`**.

Si falta `TelemetryProbeMod` → `install_ue4ss_probe.bat`.

Ruta log:
`...\Train Sim World 6\WindowsNoEditor\TS2Prototype\Binaries\Win64\UE4SS.log`

## Teclas in-game

| Contexto | Tecla | Acción |
| -------- | ----- | ------ |
| Probe    | (auto) | Probe ON al cargar |
| Probe    | F7    | Apagar / encender probe |
| Probe    | F8    | Volcar GetData al log |
| Explorer | F5    | HUD batch (amps lab) |
| Explorer | F6    | `controls.json` (+ puertas `lua.doors[]`) |
| Explorer | F7    | Otros exports lab (ver VEHICLE_LAB) |
