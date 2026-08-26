# TSW6 HTTPAPI — índice de catálogos

Referencia de los árboles bajo `Root/*` en la HTTPAPI de TSW6 (`-HTTPAPI`, puerto `31270`).

**Origen de los dumps (sesión real):**
`Desktop\investigacion tsw 6\apis\` · captura **2026-08-18 UTC** · Class 323 · Cross-City /
Lichfield City (andén 2) · servicio `2R17`.

| Árbol | Dump JSON | Tamaño | Catálogo | Interés autopilot / física |
| --- | --- | --- | --- | --- |
| **DriverAid** | `tsw-api-export-DriverAid-…json` | ~14 KB | [DRIVERAID_API.md](DRIVERAID_API.md) | ✅ Límites, gradiente, estaciones, señales |
| **CurrentFormation** | `tsw-api-export-CurrentFormation-…json` | ~9 MB | [CURRENTFORMATION_API.md](CURRENTFORMATION_API.md) | ✅ **Física tren**: masa, freno aire, esfuerzos, HUD |
| **DriverInput** | `tsw-api-export-DriverInput-…json` | ~1.6 MB | [DRIVERINPUT_API.md](DRIVERINPUT_API.md) | ✅ Mandos **escribibles** (PATCH `/set`) |
| **Player** | `tsw-api-export-Player-…json` | ~57 KB | [PLAYER_API.md](PLAYER_API.md) | 🟡 `GetDriverAidData`, posición, speeding |
| **TimeOfDay** | `tsw-api-export-TimeOfDay-…json` | ~2 KB | [TIMEOFDAY_API.md](TIMEOFDAY_API.md) | 🟡 Reloj mundo / horario escenario |
| **VirtualRailDriver** | `tsw-api-export-VirtualRailDriver-…json` | ~12 KB | [VIRTUALRAILDRIVER_API.md](VIRTUALRAILDRIVER_API.md) | ❌ Debug teclado virtual (no producción) |

---

## Mapa rápido: ¿de dónde sale cada dato hoy?

| Necesitas… | Fuente TSW6 hoy | HTTPAPI alternativa |
| --- | --- | --- |
| Velocidad, muesca UK, aceleración | Probe `HUD_Get*` → `GetData.txt` | `CurrentFormation/0.Function.HUD_Get*` |
| Gradiente, límite, cola límites | Probe `GetDriverAidData` ~20 Hz | `DriverAid.Data` |
| Estaciones programadas | HTTP `DriverAid.TrackData` ~2 s | + `tsw_hud.db` |
| Decel aprendida por muesca | `logs/profiles/*.json` | — |
| Masa del consist / carga | ❌ no integrado | `CurrentFormation/*/Simulation/*.Mass` |
| Presión cilindro / MR | 🟡 probe `brake_cyl_bar` | `BrakeCylinder_*_Pressure` |
| Esfuerzo tracción / freno (N) | 🟡 `BrakeEffort` parado B1–B2 | `HUD_GetTractiveEffort` |
| Adherencia / patinaje | ❌ (solo `HUD_GetIsSlipping` en probe futuro) | `Axle_*_CurrentTrackAdhesion`, `TM_*_Slip` |
| Escribir mandos | IPC `SendCommand.txt` (preferido) | `DriverInput/<control>.InputValue` |

---

## Prioridad para «más física» (debate)

**Validado in-game 2026-08-26 (Class 323, HTTPAPI en vivo):**

| Campo | Veredicto | Observado |
| --- | --- | --- |
| `BrakeEffort (N)` | 🟡 **B1–B2 sí** | Tren **casi parado**: B1 ≈ **5921 N**, B2 ≈ **9347 N**; escala con muesca |
| `BrakeEffort (N)` en B3 | ❌ Basura | B3 (`brk=1`): **~4.8×10²⁰ N** — sentinel / overflow; **filtrar** |
| `BrakeEffort` en marcha | ❌ Suele 0 | Frenando a ~15 m/s: **0 N** aunque `acc < 0` y `P21` sube |
| `BrakeCylinder_2_1.Pressure_BAR` | ✅ **Sí usar** | Escala estable: B1 **2.6** → B2 **3.5** → B3 **4.3** BAR (parado); en marcha hasta ~5.3 |
| `HUD_GetBrakeGauge_1` | ❌ Inútil 323 | Agujas `0 Pa` siempre en sesión probada |

Orden sugerido tras la validación:

1. **`BrakeCylinder_*_Pressure`**— fill time real (`brake_cyl_bar` en probe).**Siempre fiable.**
2. **`BrakeEffort (N)`** — esfuerzo en N cuando `|acc|≈0` y valor &lt; 50 kN; **no confiar en B3**

   ni en marcha sin repetir prueba.

3. **Masa por vehículo** (`ClampPowerInput.Mass`).
4. **`CurrentTrackAdhesion` / `Slip`**.
5. **`DriverAid.trackHeights`**.

Comando rápido de prueba (juego con `-HTTPAPI`):

```bat
```

Sesión GUI (opción 1) o guiada consola. CSV detallado en `logs/brake_physics/` + informe de calidad.

Comando manual puntual:

```bat
```

Nada de lo anterior **sustituye** DriverAid para planning; **complementa** `physics.py` y el
learner.

---

## Cómo refrescar tras un update de TSW

1. Arrancar TSW6 con `-HTTPAPI`, cabina Class 323 (u otro tren de prueba).
2. Exportar cada raíz con RailBridge / crawler (`telemetry_subtree`).
3. Guardar en `Desktop\investigacion tsw 6\apis\` con timestamp.
4. Comparar con los catálogos de esta carpeta; actualizar tablas «Estado» y bitácora.

---

## Referencias TSW6

| Archivo | Relación |
| --- | --- |
| [ARQUITECTURA.md](ARQUITECTURA.md) | Probe vs HTTP vs IPC |
| [FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md) | Constantes y learner |
| [BRAKE_V2.md](BRAKE_V2.md) | `physics.py`, coordinator |
| [FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md) | Ventana APPLY (metros → física) |
| [PENDIENTE_DYNAMICHUD.md](PENDIENTE_DYNAMICHUD.md) | Roadmap probe |

#### Última revisión catálogos: 2026-08-26
