# Laboratorio L0.6f — amperímetro (`HUD_GetAmmeter`)

**Mod:** `ApiExplorerMod` build **`20260901a`**+ · **Tecla:** **F5** (no Shift+F5)
**Plan:** [PLAN_API_EXPLORER.md](PLAN_API_EXPLORER.md) § L0.6f · HUD general:
[LAB_CAPTURA_F5.md](LAB_CAPTURA_F5.md)

> **Class 323 (cerrado):** `Amps` siempre **0** — incluso ~49 mph P2 (`20260901T211818Z`). Catálogo;
> no cablear en probe. **Al cambiar de tren, repetir todo este protocolo** — otro vehículo puede
> exponer amperímetro y RPM distinto.

---

## Tracción: ¿solo HTTP? ¿y el HUD?

| Señal | Lua F5 / probe tick | HTTP `-HTTPAPI` | 323 |
| --- | --- | --- | --- |
| `HUD_GetTractiveEffort` | ✅ lee, **siempre 0** | mismo UFunction, **0** | **Catálogo** — aguja no cableada |
| `Simulation/Axle_*/Axle.NetTractiveEffort` | ❌ `traction_probe` vacío | ✅ **651 N** (`210515Z`) | **Solo catálogo HTTP** |
| `HUD_GetAmmeter` → `Amps` | ✅ F5 | mismo valor que Lua | **Catálogo** — siempre 0 en 323 |

---

## Checklist antes de capturar

1. `install_ue4ss_explorer.bat` (build `20260901a`).
2. `ApiExplorerMod : 1` · `TelemetryProbeMod : 0` en `mods.txt`.
3. Escenario Class 323 en cabina (Cross-City recomendado).
4. Carpeta lab: `data/lab_exports/exports/<session>/` (se crea al pulsar F5).

---

## Protocolo (5 capturas)

Para cada fila: hacer la maniobra → **F5** → copiar `hud_batch.json` → `hud_batch_<nombre>.json`.

| Archivo destino | Maniobra | Esperamos en JSON |
| --- | --- | --- |
| `hud_batch_reposo.json` | Parado, release, power 0 | `Amps` ≈ 0 |
| `hud_batch_traccion_p4.json` | ~30 mph, **P3–P4** sostenido | `Amps` **> 0** |
| `hud_batch_retencion.json` | Retención / regen (power neg) | `Amps` **< 0** |
| `hud_batch_dyn_brake.json` | Solo freno eléctrico (`dyn_brake`, sin B aire) | `Amps` vs `dyn_brake` |
| `hud_batch_freno_b2.json` | B2–B3 sin power | `Amps` ≈ 0, gauges suben |

Comandos PowerShell (misma sesión, tras cada F5):

```powershell
```

Plantilla `notas_sesion.md`:

```markdown
```

---

## Analizar resultados

```bat
```

Genera tabla en consola y opcionalmente `amps_report.md`.

| Veredicto script | Significado | Acción |
| --- | --- | --- |
| `variable` | Algún `Amps` ≠ 0 | Cablear `amps` en GetData (D2) |
| `always_zero` | Todas las capturas 0 | Catálogo — usar `dyn_brake` + cilindro |
| `no_captures` | Sin `hud_batch*.json` | Repetir protocolo F5 |

**Criterio éxito:** en tracción P4 o retención, `Amps` cambia de signo respecto a reposo y
correlaciona con `power` / `dyn_brake`.

---

## Opcional: log probe en paralelo

Con **TelemetryProbeMod** ON (solo para log, no autopilot):

```bat
```

Mientras haces fila B/C, el log GetData permite cruzar `dyn_brake` y `power` a 20 Hz con el instante
del F5.

---

## Referencias

- [PLAN_API_EXPLORER.md](PLAN_API_EXPLORER.md) — L0.6d (tracción HTTP), L0.6f
- [LAB_CAPTURA_F5.md](LAB_CAPTURA_F5.md) — resto de `HUD_Get*`
