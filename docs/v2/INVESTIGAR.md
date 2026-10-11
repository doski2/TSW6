# Investigar — cola lab / campo (no backlog producto)

**Producto y orden de pasos:** solo [PLAN_V2.md](PLAN_V2.md).
**Histórico dirección V1 (RailBridge, UE4SS):**
[archive/docs/INVESTIGACION.md](../../archive/docs/INVESTIGACION.md).

Aquí van experimentos **pendientes**, evidencia **UNKNOWN** y retests ApiExplorer — sin comprometer
GetData ni P1 hasta decisión explícita (D2 / PLAN_V2).

---

## Abierto

### Tracción — `NetTractiveEffort` por Lua (L0.6d, M3a)

| Campo            | Valor                                                                                                                                                                                                                                         |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Motivo**       | HTTP ve esfuerzo en `Simulation/Axle_*/*/NetTractiveEffort` (M3a dump **≈ ±26 N** en ejes); HUD `TractiveEffort` suele **0**. Interesa **aceleración MC**, no frenado P1 (decel aprendida OK).                                                |
| **Código lab**   | ApiExplorer: `hud_batch.lua` → `lua.simulation_traction`; `config.lua` → 4 ejes + `VirtualWheel` en Shift+F5 `traction_probe`.                                                                                                                |
| **Protocolo**    | 1) F5 × 3 (neutro, **tracción MC**, freno ~15 mph). 2) Shift+F5 misma postura. 3) Comparar con GET HTTP `CurrentDrivableActor/Simulation/Axle_1_1/Axle.NetTractiveEffort`.                                                                    |
| **Éxito**        | Algún `fields_by_via.Axle.NetTractiveEffort` (o `Wheel`) **≠ 0** en Lua y coherente con HTTP en la misma postura.                                                                                                                             |
| **Si falla Lua** | Mantener catálogo HTTP; no probe 20 Hz sin D2.                                                                                                                                                                                                |
| **Docs**         | [M3A_MTA_HTTP_VS_LUA § L0.6d](M3A_MTA_HTTP_VS_LUA.md#esfuerzo-tractivo--l06d-http-sí-hud-no-lua-a-revalidar) · [PLAN_API_EXPLORER § L0.6d](PLAN_API_EXPLORER.md#l06d--esfuerzo-tractivo-no-hud--http-validado--lua-323-bloqueado--m3a-retest) |

### Masa formación M3a — `GetCurrentMass` / HTTP (paso 9 log)

| Campo         | Valor                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------ |
| **Motivo**    | Sin `ClampPowerInput.Mass` en dump Formation M3a; F-B sigue **off** en física.                               |
| **Protocolo** | En juego `-HTTPAPI`: probar `PassengerCargoModel.Function.GetCurrentMass` (y drivable); anotar valor/unidad. |
| **Docs**      | [M3A_MTA_HTTP_VS_LUA](M3A_MTA_HTTP_VS_LUA.md) · [CANAL_CONTROL § masa](../CANAL_CONTROL.md)                  |

### Confort blueprint — `MaxComfortable*` vs `accel_ms2` (L0.6h)

| Campo         | Valor                                                                                                                                                                                                                      |           |                                    |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ---------------------------------- |
| **Motivo**    | M3a: **0,447 m/s²** accel/decel en `RailVehiclePhysicsComponent`; techo referencia aceleración suave.                                                                                                                      |           |                                    |
| **Protocolo** | JSONL: ¿`                                                                                                                                                                                                                  | accel_ms2 | ` supera ~0,45 m/s² con MC fuerte? |
| **Docs**      | [M3A_MTA_HTTP_VS_LUA § confort](M3A_MTA_HTTP_VS_LUA.md#confort-de-aceleración--deceleración-investigación-no-p1-freno) · [PLAN_API_EXPLORER § L0.6h](PLAN_API_EXPLORER.md#l06h--confort-aceleracióndeceleración-blueprint) |           |                                    |

---

## Cerrado / archivado aquí

#### (Mover filas desde «Abierto» cuando haya FACT reproducible o decisión «no perseguir».)

---

## Relacionados

- [PLAN_API_EXPLORER.md](PLAN_API_EXPLORER.md) · [VEHICLE_LAB.md](VEHICLE_LAB.md) ·

  [COMPARATIVA_323_M3A.md](COMPARATIVA_323_M3A.md)
