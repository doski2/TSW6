# ApiExplorerMod

Mod UE4SS de **laboratorio** — descubre campos Lua y los correlaciona con rutas HTTPAPI.

**No usar junto al autopilot:** desactiva este mod y deja solo `TelemetryProbeMod` en producción.

Plan: [docs/v2/PLAN_API_EXPLORER.md](../../docs/v2/PLAN_API_EXPLORER.md)

## Instalación

Desde la **raíz del repo** (donde está `mods\ApiExplorerMod`):

```bat
install_ue4ss_explorer.bat
```

Equivalente: `scripts\ue4ss\install_ue4ss_explorer.bat`

Si falla «no se encuentra main.lua», ejecuta el `.bat` desde el repo clonado completo, no una copia suelta del script.

O copia `mods/ApiExplorerMod/Scripts/` a:

`Train Sim World 6\...\Mods\ApiExplorerMod\Scripts\`

Añade en `mods.txt`:

```text
ApiExplorerMod : 1
```

**Importante:** con autopilot activo, pon `ApiExplorerMod : 0` y `TelemetryProbeMod : 1`.

## Uso en cabina

| Tecla | Modo | Salida |
| --- | --- | --- |
| F5 | `hud_batch` | `HUD_Get*` + `http_guess` |
| F6 | `controls` | inventario palancas + `layout_hint` |
| F7 | `driver_aid` | DriverAid escalares + C1 candidatos |
| Shift+F5 | `formation` | cilindros / Simulation |
| Shift+F6 | `reflect_shallow` | props y funcs del drivable |
| Shift+F7 | `correlate_tick` | marca para correlator Python |

**F10** abre la consola UE (`ConsoleEnablerMod : 1` en `mods.txt`) — no es el explorer.

Exports (tras `install_ue4ss_explorer.bat`):

```text
data/lab_exports/exports/<session>/
  session.json
  hud_batch.json
  controls.json
  ...
```

El juego **no puede** escribir en `mods/` (Program Files). El instalador crea
`%USERPROFILE%\Documents\TSW6\lab_root.txt` apuntando al repo. Override: variable de entorno
`TSW6_LAB_DIR`.

**Qué recopila F5 y protocolo de capturas:** [docs/v2/LAB_CAPTURA_F5.md](../../docs/v2/LAB_CAPTURA_F5.md)
