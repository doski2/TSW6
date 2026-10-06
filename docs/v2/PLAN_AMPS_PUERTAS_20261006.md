# Plan campo — amperios (`amps`) y puertas (`doors_telem`)

**Fecha:** 2026-10-06 · **Tren principal:** M3a MNR (`RVM_NYH_MNR_M3a-A_C` / B_C) · **Opcional
control:** Class 323

**Referencias:** [telemetry/RVM_Class323_M3a_LUA_HTTP.md](telemetry/RVM_Class323_M3a_LUA_HTTP.md) ·
[CANAL_CONTROL.md](../CANAL_CONTROL.md) · [VEHICLE_LAB.md](VEHICLE_LAB.md) ·
[PLAN_ACTUACION_MC.md](PLAN_ACTUACION_MC.md) (dwell / FSM puertas)

**Regla mods (no mezclar en la misma sesión):**

| Mod                   | `mods.txt`                                     | Para qué                                                  |
| --------------------- | ---------------------------------------------- | --------------------------------------------------------- |
| **TelemetryProbeMod** | `TelemetryProbeMod : 1` · `ApiExplorerMod : 0` | `GetData` / JSONL P1 — `amps`, `doors_telem`, `doors_dmi` |
| **ApiExplorerMod**    | `ApiExplorerMod : 1` · `TelemetryProbeMod : 0` | Lab F5/F6 — `hud_batch`, `lua.doors[]`                    |

**Build mínimo en juego:** probe y explorer **`20261006a`** (copiar desde repo:
`install_ue4ss_probe.bat` / `install_ue4ss_explorer.bat`).

---

## Ya hecho en repo (no repetir en campo salvo reinstalar)

- [x] GetData: clave **`amps=`** (`HUD_GetAmmeter`) — D2 en [CANAL_CONTROL.md](../CANAL_CONTROL.md)
- [x] JSONL P1: campo **`amps`** en `trace.py`
- [x] Probe: lista puertas ampliada (`PassengerDoor_FL`… + `_1`…`_8`); sin hijo UE → **no** emitir

  `doors_telem`

- [x] Explorer F6: bloque **`lua.doors[]`** en `controls.json`
- [ ] **Validación in-game** (este plan)

### Bitácora campo (chat)

| Fecha       | FACT                                                                                     |
| ----------- | ---------------------------------------------------------------------------------------- |
| 2026-10-06  | GetData: **`amps=`**; **`doors_telem=1`** abierto                                        |
| 2026-10-07  | Monitor probe: puertas **abierto/cerrado** (`doors=1/—` ↔ `0/—`); **amps** al acelerar/frenar (M3a B_C) |

---

## Cómo reportar cada fase

Copia en el chat (o en `notas_sesion.md` de la carpeta lab):

1. Ruta del log: `logs\ue4ss_probe_YYYYMMDD_HHMMSS.txt` (o JSONL `logs\v2\…` si usaste `trace`)
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

**Archivo:** `logs\ue4ss_probe_YYYYMMDD_HHMMSS.txt` — al cerrar, pásame **esa ruta** en el chat.
CSV incluye `amps`, `doors_telem`, `doors_dmi`, `mc_input`; cada muestra lleva también `# raw:` GetData completo.

Opcional P1 JSONL: `V2\run_p1_session.bat trace gct-mnr` → `logs\v2\*_probe-only.jsonl` (dwell / replay).

**Si el `.bat` falla al instante:** Python — `.venv` en la raíz o Python 3.9+ en PATH.

**Comprobar en el log (`# raw:`):**

- `amps=` en reposo y en tracción (M3a suele ≠ 0 en tracción; 323 puede ~0 — L0.6f).
- `doors_telem` coherente con puertas cerradas/abiertas si hiciste el paso en andén.

**Criterio cierre fase 1:**

- [x] `amps` presente en GetData con probe `20261006a` (2026-10-06)
- [ ] Al menos una muestra **reposo** y una **tracción** anotadas (valor + `speed_ms` / `spd_mph`)

**Si falla:** pegar una línea GetData completa + `vehicle=`; no tocar P1 todavía.

---

## Fase 2 — Amperios lab (F5, cruce opcional)

**Mod:** solo **ApiExplorerMod** (misma ruta/cabina).

**Tú:**

1. `explorar_tren.bat` + auto-refresh si quieres.
2. **F5** en reposo → renombrar `hud_batch.json` → `hud_batch_00_reposo.json`
3. **F5** en tracción → `hud_batch_01_traccion.json`

**PC (opcional):**

```bat
python scripts\tools\summarize_hud_amps.py data\lab_exports\exports\<SESSION_ID> --write-report
```

**Criterio cierre fase 2:**

- [ ] `amps_report.md` o tabla con Amps reposo vs tracción
- [ ] Coherencia **FACT:** F5 lab ≈ mismo orden de magnitud que probe fase 1 (no tiene que ser

  idéntico al tick)

---

## Fase 3 — Puertas en lab (F6, nombres UE)

**Mod:** solo **ApiExplorerMod**.

**Tú en cabina (andén, servicio parado):**

| Paso | Acción                                                                                                                                      |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 3a   | Puertas **cerradas** → **F6**                                                                                                               |
| 3b   | Puertas **abiertas** (lado andén) → renombrar `controls.json` → `controls_doors_closed.json` → **F6** otra vez → `controls_doors_open.json` |

**Comprobar en GUI lab (pestaña Resumen / controls) o en JSON:

- `lua.doors[]` con **≥1** entrada y `name` UE real
- `open_hint: true` y/o `read_value` > 0 con puertas abiertas

**Criterio cierre fase 3:**

- [ ] Lista `doors` no vacía **o** documentado **UNKNOWN** (Shift+F6 `reflect_shallow` + nota en

  `notas_sesion.md`)

- [ ] Si vacío: captura pantalla / copia nombres de hijos del actor para ampliar `DOOR_PROBE_NAMES`

---

## Fase 4 — Puertas en probe (mismo log que fase 1)

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
- [ ] Log `logs\ue4ss_probe_*.txt` con `# raw:` **cerrado** y **abierto** (+ ruta en chat)
- [ ] (Opcional) JSONL `trace` si más adelante validas dwell P1 — no obligatorio para cerrar amps/puertas probe

**Impacto P1:** sin fase 4 OK, dwell B1 y bleed con puertas siguen **sin telemetría fiable** (201242Z).

---

## Fase 5 — Control 323 (opcional, 30 min)

Solo si quieres contrastar UK:

- Probe: ¿`doors_telem` true en andén con puertas abiertas?
- ¿`amps` ~0 en tracción (catálogo)?

Cierra hueco “¿solo M3a?” en [RVM_Class323_M3a_LUA_HTTP.md](telemetry/RVM_Class323_M3a_LUA_HTTP.md).

---

## Fase 6 — Cierre documentación (PC / chat)

Cuando 1–4 estén OK o bloqueadas con evidencia:

| Entrega  | Acción                                                                               |
| -------- | ------------------------------------------------------------------------------------ |
| Bitácora | Añadir fila en `PLAN_API_EXPLORER` § M3a o en `notas_sesion.md`                      |
| Contrato | Actualizar tabla puertas/amps en telemetry doc si hay FACT nuevo                     |
| Código   | Si nombre UE nuevo → ampliar `DOOR_*_NAMES` en **ambos** mods (comentario sync)      |
| P1       | Solo tras fase 4: retomar validación dwell [PLAN_ACTUACION_MC](PLAN_ACTUACION_MC.md) |

**No hacer en esta oleada:** learner por `amps`; reglas P1 nuevas; HTTP solo para puertas.

---

## Orden recomendado (una tarde)

```text
0 mods → 1+4 probe_ue4ss (amps + puertas) → 2 amps lab (opcional)
→ 3 puertas F6 (opcional) → 5 323 (opcional) → 6 docs
```

**Siguiente mensaje sugerido cuando termines fase 0–1:**

> «Fase 1 hecha — session … — amps reposo X, tracción Y — GetData OK / falla …»
