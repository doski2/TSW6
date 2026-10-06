# Telemetría Lua (rápido) vs HTTP — Class 323 y M3a MNR

**Estado:** 2026-10-06 · **Plan:** [PLAN_V2.md](../PLAN_V2.md) §4.1 (probe ~20 Hz), §4.4 (planning
HTTP ~2 s) · **Contrato GetData:** [CANAL_CONTROL.md](../../CANAL_CONTROL.md)

Tres capas (no mezclar):

| Capa                | Qué es                                                      | Frecuencia            |
| ------------------- | ----------------------------------------------------------- | --------------------- |
| **Probe Lua**       | `GetData.txt` — HUD + DriverAid escalares + mandos          | ~20 Hz                |
| **Planning HTTP**   | `DriverAid.TrackData`, masa formation (Python, hilo aparte) | ~2 s (+ `v×dt` andén) |
| **Lab ApiExplorer** | JSON en `data/lab_exports/exports/<session>/` (F5–F7)       | Manual                |

Sesiones de referencia en repo:

| Tren          | `vehicle_class`                | Carpeta lab        |
| ------------- | ------------------------------ | ------------------ |
| Class 323 DMS | `RVM_BCC_WRM_Class323_DMS_A_C` | `20260830T213100Z` |
| M3a MNR       | `RVM_NYH_MNR_M3a-A_C`          | `20261005T210550Z` |

---

## Amperios y puertas — qué teníamos de verdad (revisión 2026-10-06)

Resumen honesto: **no teníais amperios en producción**; **puertas están en el código del probe pero
no como dato fiable** en lab ni en los JSONL M3a del repo.

|                             | **Amperios**                                                     | **Puertas**                                                                                                              |
| --------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **GetData probe (~20 Hz)**  | **`amps=`** desde probe build **`20261006a`** (`HUD_GetAmmeter`) | **`doors_telem` / `doors_dmi`**; lista ampliada `PassengerDoor_FL`… + `_1`…`_8`; si ningún hijo existe → no emitir telem |
| **ApiExplorer lab (F5–F7)** | F5 `hud_batch` (igual que antes)                                 | **F6** `controls.json` → bloque `lua.doors[]` (build **`20261006a`**)                                                    |
| **JSONL P1 en repo**        | Tras probe `20261006a` incluye `amps`                            | **FACT 2026-10-06:** GetData `doors_telem=1` con puertas abiertas (M3a); JSONL `station` pendiente de pegar `session_id` |
| **Herramientas aparte**     | `summarize_hud_amps.py`, L0.6f (solo **lab** `hud_batch`)        | Tests unitarios con `doors_telem=1` en línea GetData ficticia; FSM legacy asume el contrato                              |

**INFERENCE (puertas):** probe y explorer comparten la misma lista (`DOOR_CHILD_NAMES` /
`DOOR_PROBE_NAMES`). Si ningún hijo existe → probe **no** emite `doors_telem` (no confundir con
`false`). Si el nombre UE real es otro, F6 debe mostrar `doors: []` hasta ampliar la lista.

**Amperios (D2 cableado 2026-10-06):** clave **`amps=`** en GetData + JSONL (`trace.py`). P1 no usa
amps
en reglas; validar in-game tras copiar probe `20261006a`.

---

## Amperios en GetData (`amps`)

|                 | Detalle                                    |
| --------------- | ------------------------------------------ |
| **Origen**      | `HUD_GetAmmeter` → `Amps`                  |
| **Probe build** | `TelemetryProbeMod` ≥ `20261006a`          |
| **P1**          | Solo log JSONL; no sustituye `a` aprendida |
| **323 lab**     | Catálogo `Amps=0` (L0.6f)                  |
| **M3a lab**     | Amps ≠ 0 en tracción (`210550Z`)           |

---

## Class 323 — `RVM_BCC_WRM_Class323_DMS_*`

### Layout y IPC

|                   | Valor                               |
| ----------------- | ----------------------------------- |
| **layout_hint**   | `combined`                          |
| **IPC escritura** | `PowerBrakeHandle` (muescas UK 0–8) |
| **Paquete**       | `data/vehicles/class_323.json`      |

### Probe Lua (~20 Hz) — GetData

| Clave GetData                                                   | Origen                         | Notas 323                                                            |
| --------------------------------------------------------------- | ------------------------------ | -------------------------------------------------------------------- |
| `speed_ms`, `power`, `power_neg`, `handle_notch`, `lever_notch` | HUD                            | Producción                                                           |
| `train_brake`, `loco_brake`, `dyn_brake`                        | HUD handles                    | Combined; frenos en `train_brake`                                    |
| `accel_ms2`                                                     | HUD                            |                                                                      |
| `brake_cyl_bar`                                                 | HUD gauge₁ rojo (Pa→bar)       | No Simulation Lua                                                    |
| `brake_g1_*`, `brake_g2_*`, `mr_bar`                            | HUD / Simulation MR            | Opcionales si leen                                                   |
| `max_speed_ms`, `speed_limit_ms`, `gradient_pct`                | HUD + DriverAid                |                                                                      |
| `dist_limit_cm`, `next_limit_ms`                                | DriverAid (1 cartel)           | C.3a Python                                                          |
| `odo_m`                                                         | HUD / formation                |                                                                      |
| `doors_telem`, `doors_dmi`                                      | Actor `PassengerDoor_*` + DMI  | Contrato + código probe; **sin JSONL reciente con apertura** en repo |
| `signal_red`, `signal_dist_cm`                                  | DriverAid escalares            | §3 S-Lua                                                             |
| `is_slipping`, `traction_locked`                                | HUD                            |                                                                      |
| `vehicle`                                                       | Clase UE                       |                                                                      |
| `mc_input`                                                      | —                              | **No** (solo familias MC en config probe)                            |
| **`amps`**                                                      | GetData si probe ≥ `20261006a` | Igual                                                                |

### Lab ApiExplorer (JSON, no tick)

| Archivo                                  | Tecla                 | Contenido relevante 323                                       |
| ---------------------------------------- | --------------------- | ------------------------------------------------------------- |
| `hud_batch.json`                         | F5                    | 16× `HUD_Get*` (incl. `HUD_GetAmmeter`)                       |
| `controls.json`                          | F6                    | `PowerBrakeHandle`, Reverser, MasterKey, parking, emergencia… |
| `driver_aid.json`                        | F7                    | Límite, gradiente, señal; `TrackData` = HTTP-only             |
| `formation.json` / `formation_http.json` | Shift+F5 + correlator | Catálogo Simulation; cilindro HTTP validado vs gauge          |

### HTTP (no va en GetData tick)

| Ruta / nodo                                             | Uso v2                             | 323                      |
| ------------------------------------------------------- | ---------------------------------- | ------------------------ |
| `DriverAid.TrackData` → `markers[].distanceToStationCM` | Distancia andén ~2 s               | Producción §4.4          |
| `CurrentFormation/0/Simulation/ClampPowerInput.Mass`    | Masa F-B (poll; **off** en física) | Lab validado             |
| `CurrentFormation/0/Function.HUD_*`                     | Mismo que Lua F5                   | Correlación lab, no tick |
| Cola `nextSpeedLimits[]` / `nextSignals[]`              | No P1 v2                           | Descartado tick (D3/D8)  |

---

## M3a MNR — `RVM_NYH_MNR_M3a-*`

Variantes **A_C** / **B_C**: mismos mandos MC en lab; sesión ref. **A_C** `210550Z`.

### Layout y IPC

|                  | Valor                                                        |
| ---------------- | ------------------------------------------------------------ |
| **layout_hint**  | `master_controller`                                          |
| **IPC**          | `MasterController` (`ipc_aliases`: `PowerBrakeHandle` → MC)  |
| **Paquete**      | `data/vehicles/m3a_mnr.json`                                 |
| **Actuación P1** | [PLAN_ACTUACION_MC.md](../PLAN_ACTUACION_MC.md) — `mc_input` |

### Probe Lua (~20 Hz) — GetData

| Clave GetData                                                          | Origen                               | Notas M3a                                                                                  |
| ---------------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------ |
| Igual que 323 (velocidad, límites, gradiente, señal C1, slip, gauges…) | HUD + DriverAid                      |                                                                                            |
| **`mc_input`**                                                         | `MasterController.CurrentInputValue` | **Sí** en familias NYH/M3a                                                                 |
| `train_brake` / handles HUD                                            | `HUD_GetTrainBrakeHandle` etc.       | MC; no sustituye `mc_input`                                                                |
| `doors_telem`, `doors_dmi`                                             | Mismo código probe que 323           | **FACT 2026-10-06:** `doors_telem=1` en GetData (abiertas); cerradas: revalidar 0/ausente  |
| **`amps`**                                                             | GetData                              | **FACT 2026-10-06:** `amps=` presente en GetData (valores reposo/tracción: anotar en plan) |
| **`lua.doors` en F6**                                                  | Tras re-F6 con explorer `20261006a`  | Igual                                                                                      |

### Lab ApiExplorer (JSON)

| Archivo                | Tecla      | Contenido relevante M3a                                                   |
| ---------------------- | ---------- | ------------------------------------------------------------------------- |
| `hud_batch.json`       | F5         | Mismos 16 `HUD_Get*` que 323; amperímetro y esfuerzo vivos                |
| `controls.json`        | F6         | Solo **3** levers: MasterController (7 notches), Reverser, MasterKey      |
| `driver_aid.json`      | F7         | Señal US (`signalAspectClass`, `distanceToSignal`); sin puertas en export |
| `formation.json`       | Shift+F5   | Lua Simulation **parcial** (sin presiones numéricas)                      |
| `formation_http.json`  | correlator | p. ej. `BrakeCylinder_Direct_P` ~1,01 bar; tracción eje vía HTTP          |
| `reflect_shallow.json` | Shift+F6   | Árbol Simulation / nombres nodo                                           |

### HTTP (planning + lab)

| Ruta / nodo                                | Uso                   | M3a (`210550Z`)                                |
| ------------------------------------------ | --------------------- | ---------------------------------------------- |
| `DriverAid.TrackData`                      | Andén GCT-MNR         | Igual canal que 323                            |
| `ClampPowerInput.Mass`                     | F-B (off)             | Poll opcional                                  |
| `Simulation/BrakeCylinder_Direct_P.*`      | Lab / learner estudio | HTTP OK; muchos `BrakeCylinder_2_1` GET fallan |
| `Simulation/Axle_*/Axle.NetTractiveEffort` | Catálogo              | HTTP OK; Lua traction_probe vacío              |
| `Function.HUD_GetAmmeter`                  | Duplica F5            | No necesario en tick si probe lee HUD          |

---

## Comparativa rápida 323 vs M3a

| Tema                    | Class 323                                    | M3a MNR                                                           |
| ----------------------- | -------------------------------------------- | ----------------------------------------------------------------- |
| Mandos lab F6           | ~7 componentes (`PowerBrakeHandle`…)         | 3 (MC + reverser + llave)                                         |
| `mc_input` GetData      | No                                           | Sí                                                                |
| Amps GetData / JSONL    | **Sí** (`amps=`, probe `20261006a`)          | **Sí**                                                            |
| Puertas probe / JSONL   | Código sí; sin `doors_telem=true` en `logs/` | GetData `doors_telem=1` abierto (2026-10-06); JSONL por confirmar |
| `HUD_GetAmmeter` lab F5 | Catálogo (0 A)                               | Vivo en tracción                                                  |
| Cilindro producción     | HUD gauge₁                                   | Igual diseño; MR ~10 bar en gauge blanco (lab)                    |
| Simulation presión tick | No (HUD)                                     | No (HUD); HTTP lab para Direct_P                                  |
| Señal P1                | UK Stop enum                                 | US `signalAspectClass` (validar C1 MNR)                           |

---

## Relacionados

- [PLAN_API_EXPLORER.md](../PLAN_API_EXPLORER.md) · [VEHICLE_LAB.md](../VEHICLE_LAB.md) ·

  [LAB_CAPTURA_AMPS.md](../LAB_CAPTURA_AMPS.md)

- Herramienta lab amps: `tsw6.lab.lab_export.extract_amps_snapshot` (desde `hud_batch.json`)
