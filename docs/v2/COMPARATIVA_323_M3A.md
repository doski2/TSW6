# Class 323 vs M3a MNR — qué extraemos y qué usa el producto

**Audiencia:** campo y P1 · **Contrato común:** [CANAL_CONTROL.md](../CANAL_CONTROL.md) · **Detalle
técnico:**
[telemetry/RVM_Class323_M3a_LUA_HTTP.md](telemetry/RVM_Class323_M3a_LUA_HTTP.md)

**Alcance producto hoy:** **M3a** en GCT-MNR. El **323** fue el primer tren con lab L0 cerrado;
muchas piezas del probe son **compartidas** (mismo mod, mismas claves GetData).

---

## Misma tubería (los dos trenes)

| Capa         | Qué es                                | Frecuencia |
| ------------ | ------------------------------------- | ---------- |
| **Probe**    | `GetData.txt` → Python / JSONL        | ~20 Hz     |
| **Planning** | `DriverAid.TrackData` (andén, cartel) | ~2 s HTTP  |
| **Lab**      | ApiExplorer F5–F7 (opcional)          | Manual     |

**Grabar probe:** `probe_ue4ss.bat` → `logs/probe/<stamp>/` ([PROBE_LOGS.md](PROBE_LOGS.md)).

---

## Identificación en juego

|                     | Class 323                      | M3a MNR                           |
| ------------------- | ------------------------------ | --------------------------------- |
| **Clase UE (ej.)**  | `RVM_BCC_WRM_Class323_DMS_A_C` | `RVM_NYH_MNR_M3a-A_C` / `M3a-B_C` |
| **Paquete repo**    | `data/vehicles/class_323.json` | `data/vehicles/m3a_mnr.json`      |
| **Ruta P1 típica**  | Birmingham Cross-City          | `gct-mnr` (Grand Central)         |
| **Lab ref. (repo)** | `20260830T213100Z`             | `20261005T210550Z`                |

---

## Mandos e IPC (lo que escribimos al tren)

|                                       | Class 323                                                                   | M3a MNR                                                                  |
| ------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| **Layout P1**                         | `combined` — palanca UK 0–8                                                 | **Master controller** — ver [PLAN_ACTUACION_MC.md](PLAN_ACTUACION_MC.md) |
| **IPC principal**                     | `PowerBrakeHandle` (muescas)                                                | `MasterController` (alias IPC: `PowerBrakeHandle` → MC en paquete)       |
| **Lab F6 (mandos)**                   | ~7 palancas (freno combinado, reverser, llave, parking, emergencia, regen…) | **3** (MC, reverser, llave)                                              |
| **`mc_input` en GetData**             | **No** (probe no lo emite en familia 323)                                   | **Sí** — fracción MC 0..1, feedback actuación P1                         |
| **`lever_notch` / `train_brake` HUD** | Fuente útil UK (combined)                                                   | Presentes pero **no** sustituyen `mc_input` en M3a                       |

---

## GetData probe — señales que **sí usamos** en P1 (ambos donde aplica)

| Clave                                              | Uso Python               | 323                                   | M3a                          |
| -------------------------------------------------- | ------------------------ | ------------------------------------- | ---------------------------- |
| `speed_ms`, `accel_ms2`                            | Física, frenado, display | Sí                                    | Sí                           |
| `speed_limit_ms`, `dist_limit_cm`, `next_limit_ms` | Cartel / `limit_brake`   | Sí                                    | Sí                           |
| `gradient_pct`                                     | Física                   | Sí                                    | Sí                           |
| `odo_m`                                            | Estaciones / planning    | Sí                                    | Sí                           |
| `signal_red`, `signal_dist_cm`                     | Emergencia / C1          | UK (enum Stop)                        | US — **validar** aspecto MNR |
| `vehicle`                                          | Resolver paquete G-B     | Sí                                    | Sí                           |
| `doors_telem`, `doors_dmi`                         | Dwell / FSM puertas      | Código probe; campo 323 no priorizado | **FACT** probe `001325` 0↔1  |
| `brake_cyl_bar`, gauges `brake_g1_*`, `mr_bar`     | Contexto aire / learner  | HUD ~1,6 bar típico UK                | HUD ~8–11 bar reposo MC      |
| `is_slipping`, `traction_locked`                   | Log / futuro handler     | Sí                                    | Sí                           |

---

## GetData — señales **log / estudio** (no regla P1 hoy)

| Clave                                | Origen           | 323 (observado)                                                | M3a (observado)                                                            |
| ------------------------------------ | ---------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------- |
| **`amps`**                           | `HUD_GetAmmeter` | Probe ≥ `20261006a`; lab F5 suele **~0 A** en tracción (L0.6f) | Probe **±cientos A** en tracción/freno (`amp.bat`, logs `001325`/`233912`) |
| `power`, `handle_notch`, `dyn_brake` | HUD              | Combined UK                                                    | MC; correlación distinta a muesca UK                                       |

**M3a:** plan amps/puertas **cerrado** —
[PLAN_AMPS_PUERTAS_20261006.md](PLAN_AMPS_PUERTAS_20261006.md).

---

## HTTP (planning, no va en tick GetData)

| Dato                               | Uso v2                        | 323                   | M3a                        |
| ---------------------------------- | ----------------------------- | --------------------- | -------------------------- |
| `DriverAid.TrackData`              | Distancia andén, markers      | Producción            | Producción GCT-MNR         |
| `ClampPowerInput.Mass`             | Poll masa (F-B off en física) | Lab OK                | Lab / poll opcional        |
| Nodos `Simulation/BrakeCylinder_*` | Estudio lab, correlator       | Validado vs gauge HUD | Parcial; muchos GET fallan |
| `Function.HUD_*`                   | Duplica F5                    | Correlación lab       | Igual                      |

---

## Qué **no** mezclar entre trenes

1. **Umbrales de aire** del learner 323 (~1,6 bar cilindro) con M3a (~10 bar en reposo MC).
2. **`lever_notch` UK** como verdad de freno en M3a — usar **`mc_input`** +

   [PLAN_ACTUACION_MC](PLAN_ACTUACION_MC.md).

3. **Amperímetro:** en 323 el HUD puede leer 0 A con tracción; en M3a el mismo `amps=` es **útil**

   para diagnóstico, no para sustituir deceleración aprendida.

4. **Señal:** enum UK del 323 ≠ `signalAspectClass` US del M3a sin barrido L0.4b MNR.

5. **`MaxComfortableAcceleration` / `MaxComfortableDeceleration`:** parámetro blueprint DTG (~0,45

   m/s² en dump M3a) — **no** es `accel_ms2` ni el perfil de freno aprendido. Archivado en
[M3A_MTA_HTTP_VS_LUA §
confort](M3A_MTA_HTTP_VS_LUA.md#confort-de-aceleración--deceleración-investigación-no-p1-freno)
   por si más adelante se trabaja **aceleración** (MC); P1 freno no depende de ello.

---

## Resumen una línea

|                                 | 323                         | M3a                               |
| ------------------------------- | --------------------------- | --------------------------------- |
| **Producto P1 activo**          | Referencia / Cross-City     | **Sí** — GCT-MNR                  |
| **Probe compartido**            | Mismas claves GetData       | + **`mc_input`**                  |
| **Campo reciente amps/puertas** | No requerido en plan actual | `logs/probe/20261007_*`           |
| **Siguiente trabajo**           | Solo si vuelves a UK        | **PLAN_ACTUACION_MC** (dwell, MC) |

---

## Relacionados

- [M3A_MTA_HTTP_VS_LUA.md](M3A_MTA_HTTP_VS_LUA.md) — dumps HTTP M3a (escritorio) vs probe/lab
- [PLAN_V2.md](PLAN_V2.md) · [VEHICLE_LAB.md](VEHICLE_LAB.md) · [CAMPO_SCRIPTS.md](CAMPO_SCRIPTS.md)
