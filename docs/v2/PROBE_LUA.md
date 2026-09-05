# Probe Lua v2 — auditoría y mapa

**Build:** `20260905b` · **Plan:** [PLAN_V2 §4.1](PLAN_V2.md#41-tick-lua-ue4ss) ·
**Contrato:** [CANAL_CONTROL](../CANAL_CONTROL.md)

## Resumen

| Antes (v1 monolito) | Después (v2 modular) |
| --- | --- |
| ~2043 líneas en `main.lua` | ~950 líneas en 6 módulos |
| F9 + reflect + dump inventario en probe | **Eliminado** → ApiExplorerMod F6/F7 |
| FindAllOf / pairs en fallos IPC | **Eliminado** del hot path |
| C1 / 9b-a solo en parser Python | **Cableado** en probe (`signal_red`, `is_slipping`) |

## Módulos (`mods/TelemetryProbeMod/Scripts/`)

| Archivo | Rol |
| --- | --- |
| `config.lua` | `PROBE_BUILD`, intervalos, PBH 323, controles permitidos |
| `util.lua` | `unwrap_number`, muescas, helpers UE |
| `bridge.lua` | `%TEMP%\TSW6Bridge\` — GetData, IPC, ACK |
| `telemetry.lua` | Lectura HUD + DriverAid + `build_line` / `collect_sample` |
| `ipc.lua` | Mandos IPC — PBH directo en actor (323) |
| `main.lua` | Hook ReceiveTick, F7/F8, auto-start |

## GetData v2 (probe escribe)

Todo lo de [CANAL_CONTROL § Contrato](../CANAL_CONTROL.md#contrato-getdata-v2) en producción, más:

| Clave | Build | Notas |
| --- | --- | --- |
| `brake_cyl_bar` | `20260905b` | `HUD_GetBrakeGauge_1` → `RedNeedle (Pa)` ÷ 100 000 (323; lab `213100Z`). Fallback `Simulation.BrakeCylinder_*` |
| `signal_red` + `signal_dist_cm` | `20260902a` | Solo si `signalAspectClass == 2` y dist &gt; 0 |
| `is_slipping` | `20260902a` | `HUD_GetIsSlipping` |
| `traction_locked` | `20260902a` | `HUD_GetIsTractionLocked` (opcional) |

## Qué se quitó (y dónde está ahora)

| Eliminado del probe | Sustituto |
| --- | --- |
| F9 dump controles | ApiExplorerMod F6 `controls` |
| `dump_uobject_reflection` / PBH map | Lab `controls.json` → `class_323.json` |
| `dump_driver_aid` en F9 | ApiExplorerMod F7 `driver_aid` |
| `write_simulation_brake` fallback | No usado con `SAFE_LEVER_WRITE` (323) |
| `append_actor_levers_findall` | Paquete G-B + `get_direct_actor_lever` |

## Teclas

| Tecla | Acción |
| --- | --- |
| F7 | Probe ON/OFF |
| F8 | Volcar una línea GetData al log |
| ~~F9~~ | **Quitada** — usar explorer en sesión lab |

## Validación

```bat
install_ue4ss_probe.bat
python -m pytest tests/test_tsw_ue4ss_reader.py -q
```

In-game: `seq` ~20 Hz · IPC PBH · rojo en semáforo → `signal_red=1` en F8.

## Pendiente producto (no probe)

- Paso 5 PLAN_V2: `evaluate_signal_brake` en Python (P1 rojo)
- Paso 6: cargar `data/vehicles/class_323.json` en IPC (nombres sin heurística)
- 9b-b: handler slip tras matriz S1–S4
