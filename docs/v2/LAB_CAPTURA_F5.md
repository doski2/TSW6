# Laboratorio — qué recopila F5 (`hud_batch`)

**Mod:** `ApiExplorerMod` · **Tecla:** F5 (snapshot, **no** log continuo)  
**Salida:** `data/lab_exports/exports/<session>/hud_batch.json`  
**Plan:** [PLAN_API_EXPLORER.md](PLAN_API_EXPLORER.md)

---

## Cómo funciona

| | F5 explorer | Probe (`TelemetryProbeMod`) |
| --- | --- | --- |
| **Cuándo** | Solo al pulsar F5 | ~20 Hz automático con F7 ON |
| **Dónde** | `data/lab_exports/exports/` | `%TEMP%\TSW6Bridge\GetData.txt` |
| **Para qué** | Saber qué expone Lua/HTTP; comparar situaciones | Autopilot, calibración, P1 |

**F5 no sustituye al probe en marcha.** Para ver “qué hace mientras freno/acelero” en tiempo real,
usa el probe (`probe_ue4ss.bat`) o pulsa **F5 en momentos concretos** (ver protocolo abajo).

Cada F5 **sobrescribe** `hud_batch.json` de la misma sesión. Si quieres guardar varias situaciones,
copia el JSON con otro nombre (p. ej. `hud_batch_frenando.json`).

---

## Qué recopila F5 (16 `HUD_Get*`)

Validado in-game Class 323 — sesión `20260830T140413Z` (~21 m/s, power 2).

| Función Lua | Campos típicos en JSON | ¿Probe GetData? | Significado (323) |
| --- | --- | --- | --- |
| `HUD_GetSpeed` | `Speed (ms)` | ✅ `speed_ms` | Velocidad m/s (×2.24 → mph) |
| `HUD_GetAcceleration` | `Acceleration (ms2)` | ✅ `accel_ms2` | Aceleración longitudinal |
| `HUD_GetPowerHandle` | `power` (+ a veces `is_negative`) | ✅ `power`, `power_neg` | Muesca tracción UK (−4…+4; negativo = retención) |
| `HUD_GetTrainBrakeHandle` | `HandlePosition`, `IsActive` | ✅ `train_brake` | Freno tren (0–1; ~0.33 = B1) |
| `HUD_GetElectricBrakeHandle` | `HandlePosition`, `IsActive` | ✅ `dyn_brake` | Freno eléctrico / regen |
| `HUD_GetLocomotiveBrakeHandle` | `HandlePosition`, `IsActive` | ✅ `loco_brake` | Inactivo en 323 |
| `HUD_GetDirection` | `Direction`, `IsActive` | ❌ | Marcha adelante/atrás |
| `HUD_GetBrakeGauge_1` | `RedNeedle (Pa)`, `WhiteNeedle (Pa)` | ❌ | Manómetro cabina 1 |
| `HUD_GetBrakeGauge_2` | idem | ❌ | Manómetro cabina 2 |
| `HUD_GetMaxPermittedSpeed` | `max_speed`, `is_active` | ✅ `max_speed_ms` | Techo ATS (a menudo inactivo) |
| `HUD_GetIsSlipping` | `IsSlipping` | ❌ (candidato C1 física) | Patinaje |
| `HUD_GetIsTractionLocked` | `IsTractionLocked` | ❌ | Bloqueo tracción |
| `HUD_GetTractiveEffort` | esfuerzo N / presión | 🟡 `brake_cyl_bar` parcial | Esfuerzo freno/tracción (B3 overflow) |
| `HUD_GetSpeedControlTarget` | `Speed (ms)`, `IsActive` | ❌ | Cruise (no 323) |
| `HUD_GetAmmeter` | `Amps` | ❌ | Amperímetro |
| `HUD_GetEngineRPM` | `Needle1/2 RPM` | ❌ | Diesel (0 en EMU) |

**HTTP:** cada clave en `http_guess` es la ruta `CurrentFormation/0/Function.<nombre>`.

---

## Qué **no** trae F5 (hace falta otro modo)

| Dato | Modo / fuente | ¿Necesario para 323 hoy? |
| --- | --- | --- |
| Límite velocidad, gradiente, cartel | Probe `GetData` o **F7** `driver_aid` (pendiente) | ✅ probe ya lo tiene |
| Odómetro `odo_m` | Probe o **Shift+F5** `formation` | ✅ probe |
| Presión cilindro `brake_cyl_bar` | Probe (`Simulation`) o formation | 🟡 learner |
| Puertas, `vehicle` string | Probe GetData | ✅ probe |
| Masa, adhesión, Simulation completa | HTTP o formation | ❌ congelado §2 PLAN |
| Nombres lever (`PowerBrakeHandle`) | **F6** `controls` | ✅ ya conocido en 323 |
| Señal roja, distancia andén | **F7** `driver_aid` (L0.4) | ⬜ C1/C2 |

**Conclusión 323:** F5 cubre la **cabina HUD** que el probe ya usa para P1. No sustituye **vía**
(DriverAid) ni **IPC** (`lever_notch`, `seq`).

---

## Protocolo: frenar / acelerar (varias fotos F5)

Objetivo: ver cómo cambian los valores **sin** log continuo.

1. Entra en cabina, carga escenario.
2. Para cada fila, haz la maniobra y pulsa **F5** inmediatamente después.
3. Copia `hud_batch.json` con nombre descriptivo (o anota en `notas_sesion.md`).

| # | Situación | Qué mirar en JSON |
| --- | --- | --- |
| 1 | Parado, freno suelto, power 0 | `Speed`≈0, `train_brake`≈0 |
| 2 | Parado, B1 | `train_brake`≈0.33 |
| 3 | Parado, B2 / B3 | `train_brake` 0.67 / 1.0; gauges suben |
| 4 | Acelerando (power +) | `Speed` sube, `Acceleration` > 0 |
| 5 | Crucero ~40 mph | `Speed` estable, `power` según muesca |
| 6 | Frenando (B1–B3) | `Acceleration` < 0, gauges, `train_brake` |

Plantilla de notas (misma carpeta `exports/<session>/`):

```markdown
# Sesión 20260830T140413Z
- hud_batch_reposo.json — parado, release
- hud_batch_b1.json — B1 fijo
- hud_batch_freno.json — frenando desde 45 mph
```

**Log continuo** (opcional): probe ON + `probe_ue4ss.bat` o `probe_ue4ss_log.bat` → línea GetData
cada ~50 ms. El explorer no hará eso (diseño: no competir con probe).

---

## ¿Tenemos “toda” la información de F5?

| Pregunta | Respuesta |
| --- | --- |
| ¿Sabemos qué es cada `HUD_Get*`? | **Sí** para los que usa el probe — ver [CURRENTFORMATION_API.md](../reference/CURRENTFORMATION_API.md) |
| ¿F5 = GetData? | **Casi** en cabina; GetData añade DriverAid, odo, doors, lever_notch |
| ¿F5 = HTTP CurrentFormation? | **Solo** el subárbol `Function.HUD_Get*` (~16 nodos de ~25k) |
| ¿Hace falta más en F5 para 323? | **No** para validar el mod; sí **varias capturas** si quieres estudiar frenos |
| ¿Errores en JSON `errors[]`? | 4 funciones con firma UE distinta en build `d`; corregido en `e` — re-F5 tras reinicio |

---

## Validación in-game (bitácora)

| Fecha | Sesión | Notas |
| --- | --- | --- |
| 2026-08-30 | `20260830T140413Z` | F5 OK — 323 en marcha ~21 m/s; 12/16 HUD OK; build `20260830d` |

---

## Referencias

- [CANAL_CONTROL.md](../CANAL_CONTROL.md) — contrato GetData probe
- [CURRENTFORMATION_API.md](../reference/CURRENTFORMATION_API.md) — catálogo HTTP/Lua
- [PLAN_API_EXPLORER.md](PLAN_API_EXPLORER.md) — F6/F7 y roadmap
