# Laboratorio por tren — Vehicle Lab

**Estado:** arranque 2026-10-03 · **Lua:** `mods/ApiExplorerMod/` · **Plan L0:**
[PLAN_API_EXPLORER.md](PLAN_API_EXPLORER.md)

Exploración de **cada tren nuevo** (Harlem M3A/M7A, …) separada del producto `V2/tsw6v2/`.
Aquí no se cambian reglas P1; se **descubre**, se **compara** con el contrato probe y se genera el
paquete G-B.

---

## Por qué no basta hoy

| Herramienta                      | Qué hace                                                 | Qué falta para un tren nuevo                          |
| -------------------------------- | -------------------------------------------------------- | ----------------------------------------------------- |
| `aprender.bat` / `learn_monitor` | Calibra decel por muesca (v1, acoplado a 323/heurística) | No unifica lab JSON + probe + puertas/señal           |
| `validar_freno.bat`              | CSV dual Lua+HTTP                                        | Lab frenos, no inventario mandos ni exports F6        |
| ApiExplorer F5–F7                | JSON en `data/lab_exports/`                              | Sin GUI que muestre **todo** junto ni diff vs GetData |
| `V2\run_p1_session`              | P1 producto                                              | No es laboratorio de cabina                           |

**Vehicle Lab** = un solo sitio: sesiones lab + telemetría viva (probe) + checklist hacia
`data/vehicles/`.

---

## Carpetas (no mezclar)

```text
```

Regla: **código en `lab/`** no entra en `V2/tests/` de producto salvo tests opcionales `lab/tests/`
más adelante.

---

## Qué exporta el Lua explorer (referencia)

Tras `install_ue4ss_explorer.bat` y F5–F7 en cabina:

| Archivo                                  | Tecla    | Uso Vehicle Lab                                                 |
| ---------------------------------------- | -------- | --------------------------------------------------------------- |
| `session.json`                           | —        | `vehicle_class`, build, timestamp                               |
| `hud_batch.json`                         | F5       | Velocidad, frenos HUD, **muescas**, amperímetro, slip, cilindro |
| `controls.json`                          | F6       | Palancas UE, `layout_hint`, notches → **G-B**                   |
| `driver_aid.json`                        | F7       | Límites, gradiente, **señal** (C1), puertas DMI                 |
| `formation.json` / `formation_http.json` | Shift+F5 | Aire, masa, ejes (catálogo; F-B off en 323)                     |

Detalle modos: [mods/ApiExplorerMod/README.md](../../mods/ApiExplorerMod/README.md).

---

## GUI Vehicle Lab (objetivo)

Paridad con lo que ya usáis en 323 en sesión / visor:

| Panel                 | Fuente lab                | Fuente probe (~20 Hz)                        |
| --------------------- | ------------------------- | -------------------------------------------- |
| Velocidad / gradiente | `hud_batch`, `driver_aid` | `speed_ms`, `gradient_pct`                   |
| Muesca / palanca      | `controls` + HUD lever    | `lever_notch`, `handle_notch`, `train_brake` |
| Aire / cilindro       | `hud_batch` gauge         | `brake_cyl_bar`                              |
| Límite cartel         | `driver_aid`              | `dist_limit_cm`, `next_limit_ms`             |
| Señal roja            | `driver_aid`              | `signal_red`, `signal_dist_cm`               |
| Puertas               | `driver_aid` / DMI        | `doors_telem`, `doors_dmi`                   |
| Vehículo              | `session.json`            | `vehicle`                                    |

**Fases GUI (alineadas con [PLAN_API_EXPLORER](PLAN_API_EXPLORER.md)):**

| Fase       | Tú en juego / PC                                            | Carpeta sesión                          |
| ---------- | ----------------------------------------------------------- | --------------------------------------- |
| prep       | Explorer instalado; copiar `templates/notas_sesion.md`      | `notas_sesion.md`                       |
| l0_2_3     | F5 → F6                                                     | `hud_batch.json`, `controls.json`       |
| l0_4       | F7                                                          | `driver_aid.json`                       |
| l0_4b      | F7 con señales US (varias pasadas; opcional renombrar JSON) | manual                                  |
| l0_6g      | F5 × estados MC (renombrar antes de cada F5)                | `hud_batch_*.json`                      |
| l0_6       | Shift+F5; luego `api_correlator.py --formation`             | `formation.json`, `formation_http.json` |
| railbridge | Copiar dumps del día                                        | `railbridge/*.json`                     |
| package    | `vehicles_json_from_lab.py` (+ `build_m3a_profile…` M3a)    | —                                       |
| probe      | `compare_lab_vs_probe.py` tras P1                           | —                                       |

Plantillas: [`data/lab_exports/templates/`](../../data/lab_exports/templates/). En GUI: pestaña
**Fases L0**.

**Asistente L0 (v1):** panel superior en `explorar_tren.bat` — **Seguir L0** (primera sesión/fase
pendiente), **Preparar PC** (notas + `railbridge/`, copia dumps RailBridge si fase catálogo),
**Correlator**, **Generar G-B**, **Saltar fase** (opcionales `l0_4b` / `l0_6g`), auto-actualizar 5 s
mientras capturas en cabina.

**Roadmap GUI código:**

1. **v0** — Sesiones, JSON, fases L0, plantillas.
2. **v1 (ahora)** — Asistente L0 + subprocess PC; probe en vivo pendiente.
3. **v2** — Matriz muescas / perfiles `logs/profiles/`.
4. **v3** — Diff CANAL_CONTROL + diff vs RailBridge catálogo.

---

## Comandos

```bat
```

Los `.bat` deben guardarse con fin de línea **CRLF** (Windows). Si solo tienen LF, `cmd` falla al
ejecutarlos.

En cabina: F5 → F6 → F7 (Harlem, cada `vehicle_class` por sesión).

Generar paquete (CLI, hasta integrar en GUI):

```bat
```

Harlem M3A (lab `20261003T144934Z` + dumps RailBridge del mismo día):

```bat
```

Salida: `data/vehicles/m3a_mnr.json` (`layout`: `master_controller`).

---

## Harlem M3A / M7A

1. Sesión lab por variante (o una si F6 idéntico).
2. Vehicle Lab → revisar exports.
3. JSON en `data/vehicles/`.
4. `V2\test_ipc.bat` con probe.
5. `V2\run_p1_session.bat limit` — validar reglas P1 sin tocar REGLAS hasta tener JSONL.

---

## Relacionados

- [PLAN_API_EXPLORER.md](PLAN_API_EXPLORER.md) · [CANAL_CONTROL.md](../CANAL_CONTROL.md) ·

  [CODIGO_V2.md](CODIGO_V2.md)

- [telemetry/RVM_Class323_M3a_LUA_HTTP.md](telemetry/RVM_Class323_M3a_LUA_HTTP.md) — probe vs HTTP

  por tren (323 + M3a)

- [PLAN_AMPS_PUERTAS_20261006.md](PLAN_AMPS_PUERTAS_20261006.md) — plan campo amps + puertas (fases)
