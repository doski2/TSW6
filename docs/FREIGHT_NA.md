# Freight NA — SD40-2 y multi-mando

Trenes diesel norteamericanos con **tracción + 3 frenos** separados (layout `freight_na`).

---

## Layouts

### `combined` (UK EMU — Class 323)

Un solo handle 0–8: 0 = freno máx … 4 = neutro … 8 = tracción máx.
Perfil ejemplo: `logs/profiles/RVM_BCC_WRM_Class323_DMS_A_C.json`

### `freight_na` (SD40-2, ES44, etc.)

| Eje                 | En juego      | Telemetría API (HUD)                  |
| ------------------- | ------------- | ------------------------------------- |
| Tracción            | Muescas 0–8   | `HUD_GetPowerHandle` → `handle_notch` |
| Freno automático    | % 0–1         | `HUD_GetTrainBrakeHandle`             |
| Freno independiente | % -1–1        | `HUD_GetLocomotiveBrakeHandle`        |
| Freno dinámico      | Muescas → 0–1 | `HUD_GetElectricBrakeHandle`          |

Escritura API: `Throttle`, `AutomaticBrake`, `IndependentBrake`, `DynamicBrake`
(no `PowerBrakeHandle`).

Plantilla esquema: `logs/control_schemas/freight_na_railbridge_v3.json`
(nombre histórico; no depende de RailBridge).

---

## Fases del plan

| Fase | Estado | Entregable                                    |
| ---- | ------ | --------------------------------------------- |
| 0    | ✅     | Esquemas en `logs/control_schemas/`           |
| 1    | ✅     | `control_layout.py`, `TrainState` multi-mando |
| 2    | ✅     | `FreightLearner`, JSON v2                     |
| 3    | ✅     | Monitor 4 matrices en `learn_monitor.py`      |
| 4    | ⬜     | `brake_selector.py` — qué freno usar          |
| 5    | ⬜     | `handle_controller` rama freight + API        |
| 6    | ⬜     | P3 predictivo 8 muescas tracción              |

**Siguiente:** Fase 4 — selector auto / ind / dyn según situación (bajada, parada, límite).

---

## SD40-2 validado (2026-06-13)

| Eje        | Campo                                     | Rango    |
| ---------- | ----------------------------------------- | -------- |
| Tracción   | `throttle_notch`                          | 0–8      |
| Freno auto | `train_brake_handle.handle_position`      | 0.0–1.0  |
| Freno ind  | `locomotive_brake_handle.handle_position` | -1.0–1.0 |
| Freno dyn  | `electric_brake_handle.handle_position`   | 0.0–1.0  |

Detalle sesión: `logs/control_diag_BNSF_SD40-2_C_20260613_180536.txt`

---

## Calibración

`aprender.bat` → opción **2** (mercancías, 2 mph mín.).

Orden sugerido cuando las matrices freight estén completas:

1. Tracción — todas las muescas, bandas 0–30 / 30–60 / 60+ mph
2. Train brake — llano, 20–50 mph
3. Dyn brake — bajadas >0.5%, 25–45 mph
4. Ind brake — paradas, 5–20 mph

Regla: en cada ventana de 2 s solo debe moverse **un eje**; si no, la muestra se descarta.

---

## Archivos clave

| Archivo                | Rol                                 |
| ---------------------- | ----------------------------------- |
| `freight_learner.py`   | Learner multi-eje                   |
| `learn_monitor.py`     | UI matrices freight                 |
| `control_layout.py`    | Detecta `combined` vs `freight_na`  |
| `train_state.py`       | Estado con 4 mandos                 |
| `handle_controller.py` | Hoy solo `combined`; Fase 5 freight |

Plan histórico completo: [archive/docs/FREIGHT_NA_PLAN.md](../archive/docs/FREIGHT_NA_PLAN.md)
