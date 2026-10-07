# Plan campo — amperios (`amps`) y puertas (`doors_telem`)

**ESTADO: CERRADO (M3a, 2026-10-08)**

**Fecha:** 2026-10-06 · **Alcance:** solo **M3a MNR** (`RVM_NYH_MNR_M3a-A_C` / B_C). Otros trenes: fuera de

este plan hasta que se abra uno nuevo.

**Referencias:** [CANAL_CONTROL.md](../CANAL_CONTROL.md) (contrato GetData) · [PROBE_LOGS.md](PROBE_LOGS.md) (carpetas `logs/probe/`) · [VEHICLE_LAB.md](VEHICLE_LAB.md) ·
[PLAN_ACTUACION_MC.md](PLAN_ACTUACION_MC.md) (dwell / FSM puertas) ·
**Scripts:** [CAMPO_SCRIPTS.md](CAMPO_SCRIPTS.md) (qué `.bat` por fase) · [BAT.md](BAT.md) (mapa completo)

### Estado — oleada M3a **cerrada** (fases 1–2–4 + doc fase 6)

| Fase | M3a |
| ---- | --- |
| 1 Amps probe | Cerrada |
| 2 `amp.bat` | Cerrada |
| 3 F6 lab | Omitida (probe basta) |
| 4 Puertas probe | Cerrada (`001325`) |
| 6 Documentación | Cerrada en repo (2026-10-08) |

**Campo habitual:** `probe_ue4ss.bat` (amps + `doors_telem`) · `amp.bat` (informe amps).

**Siguiente fuera de este plan:** dwell P1 — [PLAN_ACTUACION_MC.md](PLAN_ACTUACION_MC.md).

**Regla mods (no mezclar en la misma sesión):**

| Mod                   | `mods.txt`                                     | Para qué                                                  |
| --------------------- | ---------------------------------------------- | --------------------------------------------------------- |
| **TelemetryProbeMod** | `TelemetryProbeMod : 1` · `ApiExplorerMod : 0` | `GetData` / JSONL P1 — `amps`, `doors_telem`, `doors_dmi` |
| **ApiExplorerMod**    | `ApiExplorerMod : 1` · `TelemetryProbeMod : 0` | Lab opcional — F5 amps, F6 nombres UE (no requerido si probe tiene puertas) |

**Build mínimo en juego:** probe y explorer **`20261006a`** (copiar desde repo:
`install_ue4ss_probe.bat` / `install_ue4ss_explorer.bat`).

---

## Ya hecho en repo (no repetir en campo salvo reinstalar)

- [x] GetData: clave **`amps=`** (`HUD_GetAmmeter`) — D2 en [CANAL_CONTROL.md](../CANAL_CONTROL.md)
- [x] JSONL P1: campo **`amps`** en `trace.py`
- [x] Probe: lista puertas ampliada (`PassengerDoor_FL`… + `_1`…`_8`); sin hijo UE → **no** emitir

  `doors_telem`

- [x] Explorer F6: bloque **`lua.doors[]`** en `controls.json`
- [x] **Validación in-game M3a** (amps + `doors_telem` en probe — 2026-10-08)

### Bitácora campo (chat)

| Fecha       | FACT                                                                                     |
| ----------- | ---------------------------------------------------------------------------------------- |
| 2026-10-06  | GetData: **`amps=`**; **`doors_telem=1`** abierto                                        |
| 2026-10-07  | Monitor probe: puertas/amps OK (M3a B_C)                                                 |
| 2026-10-07  | Log **`ue4ss_probe_20261007_001325.txt`**: 2503 muestras · puertas 0→1 @112s · 1→0 @140s · amps −488…+384 A |
| 2026-10-07  | Log **`233912`**: 1652 muestras · M3a A_C · `amp.py` **variable** · tracción ~18…378 A · frenada ~−445…−15 A |
| 2026-10-07  | **Fase 2 cerrada (M3a):** informe probe vía `amp.bat` / `amp.py` — F5 no requerido |
| 2026-10-08  | **Fase 3 F6 omitida (M3a):** puertas = `doors_telem` en `probe_ue4ss.bat`, no Explorer |
| 2026-10-08  | **Fase 6:** contrato actualizado · plan amps/puertas M3a cerrado |
| 2026-10-08  | Alcance **solo M3a** — sin fase UK / otros trenes en este plan |
| 2026-10-08  | Informes `amp_report.md` por sesión + `logs/probe/informe_combinado_amp.md` |
| 2026-10-08  | Logs probe movidos a `logs/probe/<stamp>/`; eliminados intentos vacíos `235201`/`235905` |

---

## Cómo reportar cada fase

Copia en el chat (o en `notas_sesion.md` de la carpeta lab):

1. Ruta del log: `logs\probe\YYYYMMDD_HHMMSS\ue4ss_probe_*.txt` (o JSONL `logs\v2\…` si usaste `trace`)
2. **FACT** (líneas `# raw:` o consola) — sin interpretar
3. ¿Fase OK / bloqueada?

---

## Fase 0 — PC y mods (15 min)

**Tú:**

1. Desde raíz repo: `install_ue4ss_probe.bat` y `install_ue4ss_explorer.bat` (o el que toque en la

   fase).

2. En TSW `mods.txt`, dejar **solo uno en `1`** según tabla arriba.
3. Arrancar escenario **GCT-MNR**, cabina **M3a A_C** (luego B_C si hace falta).

**Criterio OK:** consola UE4SS al cargar muestra build **`20261006a`** del mod activo.

---

## Fase 1 — Amperios en probe (GetData + JSONL)

**Mod:** solo **TelemetryProbeMod**.

**Tú en cabina:**

| Paso | Acción                                  | Qué esperamos              |
| ---- | --------------------------------------- | -------------------------- |
| 1a   | Parado, MC reposo / B0                  | Sesión corta               |
| 1b   | En tracción estable (P1–P2, ~20–40 mph) | Misma sesión o otra parada |
| 1c   | (Opcional) Freno B2 parado              | Comparar signo/magnitud    |

**Tú en PC** (desde la **raíz del repo**, TSW en cabina, **probe ON**):

```bat
probe_ue4ss.bat
```

En cabina: reposo → tracción → (opcional) freno · en andén abre/cierra puertas una vez · **Ctrl+C**.

**Archivo:** `logs\probe\YYYYMMDD_HHMMSS\ue4ss_probe_*.txt` — al cerrar, pásame **esa ruta** en el chat.
CSV incluye `amps`, `doors_telem`, `doors_dmi`, `mc_input`; cada muestra lleva también `# raw:` GetData completo.

Opcional P1 JSONL: `V2\run_p1_session.bat trace gct-mnr` → `logs\v2\*_probe-only.jsonl` (dwell / replay).

**Si el `.bat` falla al instante:** Python — `.venv` en la raíz o Python 3.9+ en PATH.

**Comprobar en el log (`# raw:`):**

- `amps=` en reposo y en tracción (M3a: ≠ 0 en tracción; ver `amp.bat`).
- `doors_telem` coherente con puertas cerradas/abiertas si hiciste el paso en andén.

**Criterio cierre fase 1:**

- [x] `amps` presente en GetData con probe `20261006a` (2026-10-06)
- [x] Log `001325`: reposo ~0 A; tracción/freno **−488…+384 A**; vmax ~19.6 mph (2026-10-07)

**Si falla:** pegar una línea GetData completa + `vehicle=`; no tocar P1 todavía.

---

## Fase 2 — Informe amps (probe) — `amp.py` — **CERRADA (M3a, 2026-10-07)**

**Objetivo:** estadísticas **min / max / media / mediana** de `amps` por régimen (reposo, tracción, frenada/regen) a partir de

`logs/ue4ss_probe_*.txt`. Herramienta **reutilizable en otros trenes** (mismo formato GetData del probe).

**Fuente principal:** probe (~20 Hz). F5 lab es **opcional** (mismo `HUD_GetAmmeter` por otro mod).

### En PC (tras fase 1)

```bat
amp.bat
amp.bat --write-report
```

*(o ruta explícita: `amp.bat logs\ue4ss_probe_20261007_233912.txt`)*

- Consola: resumen por régimen + veredicto (`variable` si hay tracción o frenada por encima del umbral).
- Con `--write-report`: `logs\<mismo_stem>_amp_report.md` (tabla markdown).
- Umbral reposo por defecto **15 A** (`--idle-threshold` si el tren tiene offset DC).
- Opcional F5 en la misma corrida: `--lab data\lab_exports\exports\<SESSION_ID>` (filas del lab al final del informe).

**Código:** `scripts/tools/amp.py` · tests: `tests/test_amp.py`.

**Criterio cierre fase 2 (M3a):**

- [x] Herramienta `amp.py` + `amp.bat` (último log por defecto, `--write-report` opcional)
- [x] Veredicto **`variable`** en logs probe: `001325` y **`233912`** (reposo |amps| &lt; 15 A; tracción/frenada en cientos de A)
- [x] **Cierre M3a** — suficiente para P1/log sin F5 lab
- [ ] *(Fuera de este plan)* otros vehículos: mismo `amp.bat` + archivar `*_amp_report.md`

*(Protocolo F5 solo si dudas del mod: bloque colapsado abajo.)*

<details>
<summary>Protocolo F5 (referencia, no requerido ahora)</summary>

**Objetivo:** mismo `HUD_GetAmmeter` que el probe, capturado en **F5** (instantánea manual). No sustituye

fase 1; confirma que el lab y el tick coinciden en orden de magnitud.

**Mod:** solo **ApiExplorerMod** (`TelemetryProbeMod : 0`). **Reiniciar TSW** tras cambiar `mods.txt`.

### Antes (5 min)

| Paso | Acción |
| ---- | ------ |
| 2.0a | `install_ue4ss_explorer.bat` — build **`20261006a`** |
| 2.0b | Misma ruta/cabina que fase 1: **GCT-MNR**, **M3a B_C** (o A_C) |
| 2.0c | Copiar plantilla: `data\lab_exports\templates\notas_sesion.md` → se rellena al crear sesión en GUI |

### En juego + PC

1. `explorar_tren.bat` (Vehicle Lab) — anota **`session_id`** (carpeta nueva bajo `data\lab_exports\exports\`).
2. Parado, MC neutro / sin tracción → **F5** → en la carpeta de sesión renombrar `hud_batch.json` →

   **`hud_batch_00_reposo.json`**.

3. Tracción estable **P1–P2**, ~20–40 mph (como fase 1) → **F5** → **`hud_batch_01_traccion.json`**.

4. *(Opcional, recomendado si frenaste fuerte en probe)* retención / freno eléctrico → **F5** →

   **`hud_batch_02_retencion.json`**.

5. En `notas_sesion.md` de la sesión: anota velocidad, muesca MC y build explorer.

### Informe PC

```bat
summarizar_amps_lab.bat <SESSION_ID>
```

(o `python scripts\tools\summarize_hud_amps.py data\lab_exports\exports\<SESSION_ID> --write-report`)

Genera consola + **`amps_report.md`** en la carpeta de sesión. Veredicto **`variable`** = Amps ≠ 0 en alguna captura.

### Cruzar con fase 1 (FACT ya en repo)

| Fuente | Reposos | Tracción / freno |
| ------ | ------- | ---------------- |
| Probe `ue4ss_probe_20261007_001325.txt` | ~0 A | **≈ −488 … +384 A** |
| F5 lab (esta fase) | `hud_batch_00_reposo` → Amps ≈ 0 | `hud_batch_01_traccion` → Amps **mismo orden** (cientos A en M3a) |

No exigir igualdad al tick: F5 es un instante; probe es ~20 Hz.

**Referencia detallada:** [LAB_CAPTURA_AMPS.md](LAB_CAPTURA_AMPS.md) (protocolo L0.6f lab; no requerido M3a).

**Criterio cierre fase 2 (solo F5):**

- [x] **N/A M3a** — sustituido por `*_amp_report.md` en `logs/` (probe)

</details>

---

## Presión de frenos (aire) — fuera del alcance amps/puertas

**Tu duda es razonable** y ya está reflejada en arquitectura, no es un fallo del probe:

| Señal | Origen en M3a (FACT doc) | Uso P1 |
| ----- | ------------------------ | ------ |
| `brake_cyl_bar`, `brake_g1_*`, `mr_bar` | **Agujas HUD** (`HUD_Get*` / gauges en probe), no Simulation Lua en tick | Feedback aire / learner — **tendencia**, no barómetro legal |
| `BrakeCylinder_Direct_P` etc. | **HTTP** en lab (`formation_http`) | Estudio; no sustituye HUD en producción |
| Simulation Lua presiones | M3a: **parcial / vacío** en tick | No esperar paridad HUD ↔ nodo UE |

En `001325` se ve **cilindro ~9,6–9,8 bar** casi estable mientras **`brake_g1_red_bar`** baja de ~2,9 → ~1,0 al soltar freno: son **distintos instrumentos** en el HUD, no el mismo sensor duplicado.

**No hace falta** “arreglar” que Lua = aguja al pixel. P1 aprende y frena con **muesca + decel observada**; la presión en GetData es **contexto**, no contrato de física DTG.

Si más adelante quieres estudiar aire: lab F5 gauges + correlator HTTP ([VEHICLE_LAB.md](VEHICLE_LAB.md) L0.6g) — **otro plan**, no esta oleada.

---

## Fase 3 — Puertas en lab (F6) — **OMITIDA para M3a** (2026-10-08)

**Decisión:** la telemetría de producto es **`doors_telem`** en el **probe** (`probe_ue4ss.bat`), no `lua.doors[]` del Explorer.

F6 solo aporta inventario UE / depuración Lua; **no sustituye** ni duplica lo que P1 consume por GetData.

**Mod:** solo **ApiExplorerMod** — **no abrir** salvo tren sin `doors_telem` en probe.

**PC:** `explorar_tren.bat` (referencia abajo). Detalle: [CAMPO_SCRIPTS.md](CAMPO_SCRIPTS.md).

**Tú en cabina (andén, servicio parado):**

| Paso | Acción                                                                                                                                      |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 3a   | Puertas **cerradas** → **F6**                                                                                                               |
| 3b   | Puertas **abiertas** (lado andén) → renombrar `controls.json` → `controls_doors_closed.json` → **F6** otra vez → `controls_doors_open.json` |

**Comprobar en GUI lab (pestaña Resumen / controls) o en JSON:

- `lua.doors[]` con **≥1** entrada y `name` UE real
- `open_hint: true` y/o `read_value` > 0 con puertas abiertas

**Criterio cierre fase 3 (M3a):**

- [x] **Omitida** — probe valida puertas (`001325`; monitor 2026-10-07)
- [ ] *(Solo otro tren / probe sin `doors_telem`)* F6 + lista `lua.doors[]` o ampliar `DOOR_PROBE_NAMES`

---

## Fase 4 — Puertas en probe — **CERRADA (M3a, 2026-10-07)**

**Mod:** solo **TelemetryProbeMod** · **Misma sesión** que fase 1 si puedes (andén).

| Paso | Puertas         | Qué mirar en `# raw:` del log                                          |
| ---- | --------------- | ---------------------------------------------------------------------- |
| 4a   | Cerradas        | `doors_telem=0` o clave ausente                                        |
| 4b   | Abiertas        | `doors_telem=1` (o `doors_dmi=1` si aparece)                           |
| 4c   | Cierre y salida | transición 1→0 en líneas sucesivas                                     |

```bat
probe_ue4ss.bat
```

**Criterio cierre fase 4:**

- [x] GetData / monitor: **`doors_telem=1`** abierto (2026-10-06)
- [x] Monitor: abierto/cerrado coherente (2026-10-07)
- [x] Log `ue4ss_probe_20261007_001325.txt`: **461** ticks `doors_telem=1`, transición 0→1 y 1→0 (2026-10-07)
- [ ] (Opcional) JSONL `trace` para dwell P1 — no obligatorio para cerrar amps/puertas probe

**Impacto P1:** con fase 4 OK en M3a, dwell puede usar `doors_telem` del tick GetData ([PLAN_ACTUACION_MC](PLAN_ACTUACION_MC.md)).

---

## Fase 6 — Cierre documentación — **CERRADA (M3a, 2026-10-08)**

| Entrega  | Estado |
| -------- | ------ |
| Bitácora plan + [PLAN_API_EXPLORER § M3a](PLAN_API_EXPLORER.md#m3a-mnr-gct--barrido-l0-en-curso) | `doors_telem` / amps probe actualizados |
| Contrato [CANAL_CONTROL.md](../CANAL_CONTROL.md) | `amps`, `doors_telem` ya en tabla D2 |
| Telemetría M3a (repo) | FACT logs `001325`, `233912` en § probe GetData |
| Código Lua `DOOR_*_NAMES` | Sin cambio — M3a OK con lista actual |
| P1 dwell | Handoff → [PLAN_ACTUACION_MC](PLAN_ACTUACION_MC.md) (no más campo amps/puertas aquí) |

**No hecho (explícito):** learner por `amps`; JSONL `trace` opcional.

---

## Orden recomendado (referencia)

```text
probe_ue4ss.bat → amp.bat   (M3a cerrado) → PLAN_ACTUACION_MC (dwell)
```

**Evidencia archivada:**

| Artefacto | Ruta |
| --------- | ---- |
| Log probe (amps + puertas B_C) | `logs/probe/20261007_001325/ue4ss_probe_20261007_001325.txt` |
| Log probe (amps A_C) | `logs/probe/20261007_233912/ue4ss_probe_20261007_233912.txt` |
| Informe amps por sesión | `.../amp_report.md` en cada carpeta |
| Informe amps combinado | `logs/probe/informe_combinado_amp.md` |

Regenerar: `amp.bat --write-report` o rutas explícitas a los `.txt` en `logs\probe\...\`.
