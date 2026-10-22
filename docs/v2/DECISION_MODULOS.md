# decision.py — flujo, módulos y reglas para no mezclar (2026-10-23)

Diagramas: [flujo de un tick](assets/p1_decision_flujo.svg) ·
[módulos y dependencias](assets/p1_decision_modulos.svg) · [vista HTML](assets/p1_decision.html).
Fuentes editables: `assets/p1_decision_flujo.dot`, `assets/p1_decision_modulos.dot`
(`dot -Tsvg … -o …`).

Punto de partida: `V2/tsw6v2/decision.py`, 1362 líneas; `evaluate_p1_tick` ocupa 287.
Los diagramas de v1 (`esqueleto_arquitectura`, `esqueleto_flujo_*`) describen `tsw6/braking/v2`
y ya no valen para esta parte.

## 1. Orden de un tick (FACT, leído de `evaluate_p1_tick`)

1. **Preparar** (`_prepare_tick`): contexto del tick y datos del vehículo.
2. **Emergencia**: si gana, el tick termina.
3. **Objetivos** (cartel, andén, señal) y **elección** de uno (`pick_p1_brake_target`).
4. **Soltar**, un solo camino por tick y en este orden: bleed de andén → soltar tras bleed →
   soltar en salida → (salvo `should_skip_p1_release`) señal heredada → cartel.
5. **Finalizar**: hay objetivo → comando → fracción MC → bloqueo de aire; si no, `idle`.
6. `ctx.decide` convierte el comando en el cable del vehículo y devuelve `LimitBrakeDecision`.

Regla del orden: una fase solo mira hacia arriba (lo ya decidido), nunca llama a una posterior.

## 2. Módulos destino

| Módulo | Contenido actual en `decision.py` | Líneas aprox. |
| ------ | --------------------------------- | ------------- |
| `decision_types` (hoja) | `LimitBrakeDecision`, `_TickCtx`, `_TickPrep` y sus métodos | 84–240 |
| `decision_prep` | `_prepare_tick`, `_escalate_cap_fn`, `_brake_applied`, `_brake_kind` | 242–253, 479–499, 584–636 |
| `decision_emergency` | `_signal_distance_m`, `_decision_from_emergency`, supresiones, `_attempt_p1_emergency` | 639–766 |
| `decision_targets` | bloques cartel / andén / señal de `evaluate_p1_tick` (hoy en línea) | 1099–1210 |
| `decision_release` | `_attempt_platform_parked_bleed*`, `_attempt_departing_brake_release`, `_attempt_signal_inherited_release`, `_attempt_p1_releases`, `_attempt_release` | 309–582, 769–832 |
| `decision_finalize` | `_overlay_active_zone_hold`, `_air_apply_block`, `_plan_reason`, `_finalize_target_decision` | 256–306, 988–1053 |
| `vehicle_adapter` (+ módulo de fracciones MC) | `_mc_station_*`, `_mc_limit_fraction`, `_station_stop_continues`, `_continue_station_stop` | 835–985 |
| `decision.py` | solo `evaluate_p1_tick` (orquestación) y `evaluate_limit_tick`; re-exporta los nombres públicos | ~150 |

## 3. Reglas para no mezclar

1. **Dependencias solo hacia abajo:** `loop → decision → fases → prep → types`, y las fases hacia el
   núcleo (`command`, `limits`, `station_*`, `signal_*`, `p1_policy`, `p1_station_gate`, `physics`).
   Ningún módulo importa `decision`. `decision_types` no importa ningún módulo de fase.
2. **Las fases no se importan entre sí.** Lo que dos fases comparten sube a `decision_prep` o
   `decision_types`.
3. **Una fase = una pregunta.** Emergencia decide «¿freno crítico?», targets calcula objetivos y no
   emite mando, release decide «¿suelto?», finalize decide «¿qué mando exacto?».
4. **Nada por vehículo fuera del adaptador.** Las fases preguntan al adaptador («¿freno aplicado?»,
   «mando para esta decel necesaria») con valores simples, no con `_TickCtx`, para que el
   adaptador no dependa de la capa de decisión. Los números de cada tren van al JSON de
   `data/vehicles/`. Operación nueva → adaptador nuevo; números nuevos → JSON.
5. **Un cambio de lógica no comparte commit con un movimiento.** Mover es cortar, pegar y ajustar
   imports; los cambios de comportamiento van después, ya con el código aislado.
6. **`decision.py` re-exporta** los nombres movidos que usan `loop.py` y los tests, para no tocar
   sus imports. Antes de mover: `grep` de nombres privados (`_attempt_*`, `_TickCtx`) en `tests/`.
7. **Tope de tamaño:** ~400 líneas por módulo de fase y ~150 para `decision.py`; si una fase lo
   supera, se parte por pregunta, no por tren.

## 4. Orden de extracción (un commit por paso, suite completa antes y después)

0. ~~Borrar `diag_station`~~ (hecho) (marcado «quitar tras 212814Z»; solo lo usa `decision.py`, import y
   llamada `log_station_tick`). `evaluate_limit_tick` se conserva: lo usa `tests/test_decision.py`.
1. ~~`decision_types`~~ (hecho).
2. ~~`decision_prep`~~ (hecho).
3. ~~`decision_emergency`~~ (hecho).
4. ~~`decision_release`~~ (hecho; aquí se alinean después los umbrales aplicar/soltar, ANALISIS §7.1 e).
5. Lógica MC al adaptador, pasando valores simples (ANALISIS §8.7).
6. `decision_targets` y `decision_finalize`; `evaluate_p1_tick` queda como orquestador.

Criterio de cierre de cada paso: 590 pruebas en verde (4 saltadas), sin diff de comportamiento
(`V2/scripts/replay_jsonl.py` re-evalúa una sesión JSONL con `evaluate_p1_tick`: guardar su
salida antes del paso y compararla después sobre `212139Z`).

### Estado (2026-10-23)

- **Hecho:** pasos 1 y 2. `decision_types.py` (173 líneas) y `decision_prep.py` (114);
  `decision.py` baja de 1362 a 1099. Nombres públicos renombrados sin guion bajo
  (`TickCtx`, `TickPrep`, `prepare_tick`, `brake_kind`, `brake_applied`, `escalate_cap_fn`);
  `LimitBrakeDecision` sigue importable desde `decision`.
- **Verificado:** 590 pruebas en verde y paridad antes/después sobre `212139Z` (8706 ticks, uno de
  cada tres): 0 diferencias en razón, fase, tipo de objetivo, `apply_now` ni mando.
- **Hecho (2026-10-23, segunda tanda):** paso 0 (`diag_station` borrado: era opt-in con
  `TSW6_DIAG_STATION=1`, nunca generó fichero y solo lo usaba `decision.py`) y paso 3
  (`decision_emergency.py`, 143 líneas; `signal_distance_m` pasa a `decision_prep` por ser
  compartido). `decision.py` queda en 950 líneas (de 1362).
- **Verificado la segunda tanda:** 590 pruebas y paridad sobre `212139Z` y `205735Z` (15 663 ticks,
  195 de ellos de emergencia): 0 diferencias.
- **Hecho (tercera tanda):** paso 4 (`decision_release.py`, 366 líneas con la guarda del parpadeo: bleed, soltar tras bleed,
  salida, señal heredada y cartel). `decide_station_neutral_release` pasa a `decision_types` como
  función (la comparten `decision_release` y `_continue_station_stop`; un test usa un `ctx` falso
  con solo `decide`). El test de `_attempt_platform_parked_bleed_release` importa ahora de
  `decision_release`. `decision.py` queda en 619 líneas (de 1362).
- **Verificado la tercera tanda:** 590 pruebas y paridad sobre las tres sesiones del 22-oct
  (28 399 ticks, uno de cada dos; 902 `release`, 4555 `platform_bleed`, 300 `emergency`): 0
  diferencias.
- **Hecho (cambio de lógica, commit aparte):** el parpadeo de ANALISIS §7.1 e.
  `decision_release._limit_plan_owns_brake` (el plan manda mientras aplique y la velocidad esté
  sobre su objetivo). Un solo punto de decisión por episodio para el cartel; los demás caminos de
  soltar quedan para freno heredado.
- **Sin hacer:** pasos 5-6.
- **Aviso:** el diff de `decision.py` mezcla este movimiento con `_mc_limit_fraction` (sin commit
  previo). Conviene commitear primero el freno analógico por cartel y después el movimiento.

### Matiz a la regla 3 (hoy no se cumple del todo)

Las fases de «objetivos» no son puras: `evaluate_limit_brake` confirma estado (`state.replace_from`)
aunque su objetivo pierda en `pick_p1_brake_target`; el bloque de andén llama a
`learner.observe_brake_decel`; y `_mc_station_stop_fraction` escribe `limit_state.station_stop_m`.
Al extraer `decision_targets` hay que conservar ese orden exacto; hacerlas puras es un cambio de
lógica aparte (regla 5).

## 5. Pendiente de decisión

- Nombre y ubicación: archivos planos `decision_*.py` en `tsw6v2/` (propuesto) o paquete
  `tsw6v2/decision/`. Lo plano evita mover imports; el paquete queda más ordenado si llegan más
  fases.
