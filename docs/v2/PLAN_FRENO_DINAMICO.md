# Plan — freno dinámico y amperios en el aprendizaje

**Estado:** fases 1 y 2 hechas en el M3a. Fases 3–4 sin código de producto.
**Validación:** en el M3a, amperios negativos al frenar no son el mando `dyn_brake`,
pero sí retención eléctrica. Sirven para no mezclar esa deceleración con la de aire.
El dinámico de mercancías sigue pendiente.

**Hecho ya (FACT):** `amps` en GetData/JSONL (`HUD_GetAmmeter`). P1 no lo usa para decidir.
`dyn_brake` es el mando eléctrico del HUD (`HUD_GetElectricBrakeHandle`).

Amperios negativos = retención (OBSERVATION de laboratorio, `LAB_CAPTURA_F5`). No es todavía
una curva de frenado.

---

## Qué no hace este plan

- No cambia la deceleración que usa el andén ni el cartel.
- No mezcla regen y freno de aire en la misma media.
- No inventa un paquete de mercancías.

## Fases

| Fase | Qué                                                                                                                               | Estado                                      |
| ---- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| 1    | Contar ticks con `amps < -1` (`LearnerProfile.note_amps`). JSONL `regen_n` si es > 0. `predict_decel` igual                       | Hecho                                       |
| 2    | Retención (`amps` < −1) no entra en la media UK. El APPLY del combinado aprende `decel_by_mc` (misma posición ~2 s)               | Hecho                                       |
| 3    | Perfil aparte `decel_by_dyn` solo si el paquete del tren declara freno dinámico                                                   | Pendiente                                   |
| 4    | El plan elige la posición con `decel_by_mc`. Hoy la fracción sigue saliendo de la fórmula fija                                    | Pendiente                                   |

## Criterio para abrir la fase 3

Una sesión, M3a o mercancías, con `regen_n` > 0 y rechazos `electric` mientras se frena. Hasta
entonces no hay curva propia del freno eléctrico.
