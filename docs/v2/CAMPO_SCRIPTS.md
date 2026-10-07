# Scripts de campo — plan amps y puertas (M3a)

**Plan:** [PLAN_AMPS_PUERTAS_20261006.md](PLAN_AMPS_PUERTAS_20261006.md) · **Mapa completo `.bat`:** [BAT.md](BAT.md)

Para **amps y puertas en M3a** basta el **probe**. Un solo flujo en juego + PC.

## Lo que sí usas (M3a)

| Qué | `.bat` |
| --- | ------ |
| Grabar telemetría (`amps`, `doors_telem`, …) | **`probe_ue4ss.bat`** |
| Informe amps (PC, tras sesión) | **`amp.bat`** |
| Instalar Lua probe (una vez / tras cambios) | `install_ue4ss_probe.bat` |

`mods.txt`: **TelemetryProbeMod : 1** · ApiExplorerMod : 0.

En andén: abre/cierra puertas durante la sesión del probe; en el log mira columnas `doors_telem` / `doors_dmi` y `# raw:`.

Carpetas: [PROBE_LOGS.md](PROBE_LOGS.md) (`logs/probe/<stamp>/`).

**No necesitas** `explorar_tren.bat` ni F6 para cerrar puertas en este plan (ya validado en log `001325`).

---

## Por fase (estado M3a)

| Fase | Estado | Script |
| ---- | ------ | ------ |
| 1 Amps probe | Cerrada | `probe_ue4ss.bat` |
| 2 Informe amps | Cerrada | `amp.bat` |
| 3 Puertas lab F6 | **Omitida** | — (solo si otro tren sin `doors_telem`) |
| 4 Puertas probe | Cerrada | mismo `probe_ue4ss.bat` + log |
| 6 Docs | Cerrada M3a | — |

---

## Explorer — solo excepción

| Mod | Cuándo | `.bat` |
| --- | ------ | ------ |
| ApiExplorerMod : 1 | Tren nuevo sin `doors_telem` en probe; o estudio F5 amps | `explorar_tren.bat` + F5/F6 |

No mezclar probe y explorer en la misma sesión TSW. Tras cambiar `mods.txt` → reiniciar juego.

### Referencia F6 (no M3a)

1. `install_ue4ss_explorer.bat`
2. `explorar_tren.bat` → F6 cerradas/abiertas → `lua.doors[]` en JSON
3. Ampliar `DOOR_PROBE_NAMES` en Lua si hace falta

---

## Fase 2 — `amp.py`

| Entrada | `amp.bat` o `python scripts/tools/amp.py` (sin args = último log) |
| `--write-report` | `logs\*_amp_report.md` |

F5 lab (opcional): `summarizar_amps_lab.bat` — **no** requerido M3a.

---

## Otros `.bat` (fuera de este plan)

P1 (`V2\run_p1_session.bat`), autopilot (`iniciar_autopilot.bat`), HUD Rust, learner, perf — ver [BAT.md](BAT.md).
