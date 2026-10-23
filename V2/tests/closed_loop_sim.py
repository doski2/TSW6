"""Simulador mínimo de lazo cerrado de la Class 323 para probar ``evaluate_p1_tick``.

Modelo deliberadamente simple, calibrado con las ventanas de freno estable de las sesiones
``20261023T211407Z``-``T223846Z`` (decel en llano: B1 ≈ 0,60, B2 ≈ 0,85, B3 ≈ 1,1 m/s²):

* la palanca sigue al mando tras ``IPC_DELAY_S``;
* el freno llega a su valor con una constante de tiempo ``FILL_TAU_S`` (llenado de cilindros);
* decel = coast + freno·rampa − componente de la pendiente.

Escenarios: andén con o sin cartel lejano (``limit_next``), carteles de velocidad intermedios
(``limit_signs``) y un semáforo (``signal_pos_m``) que sigue rojo o pasa a verde (``signal_green_at_s``).

No sustituye al juego: sirve para comparar variantes de la lógica en igualdad de condiciones
(parpadeo de muesca, cuánto queda corto el tren, si se salta un rojo) y para detectar regresiones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Optional

from replay_helpers import tick_to_snap
from tsw6v2.command import BrakeReleaseState
from tsw6v2.decision import evaluate_p1_tick
from tsw6v2.limits import LimitBrakeState
from tsw6v2.physics import get_active_physics, set_active_physics

MPH_TO_MS = 0.44704
DT_S = 0.06  # el probe escribe a ~16,7 Hz con el juego a 50 fps
IPC_DELAY_S = 0.15
FILL_TAU_S = 1.2
COAST_DECEL = 0.095
NOTCH_DECEL = {3: 0.60, 2: 0.85, 1: 1.10}  # llano; handle 3 = B1 … 1 = B3
VEHICLE = "RVM_BCC_WRM_Class323_DMS_B_C"
SIGN_PASSED_M = 8.0


@dataclass
class SimResult:
    stop_dist_m: float  # al tablón: + = paró antes; − = se pasó (None si no hay andén: 0)
    stopped: bool
    notch_changes: int  # cambios de muesca mandados (APPLY con muesca distinta de la previa)
    quick_reversals: int  # B1↔B2 en < 3 s
    commands: list[tuple[float, str, Optional[int]]] = field(default_factory=list)
    signal_margin_m: Optional[float] = None  # al semáforo al parar: + = antes del poste
    passed_red: bool = False  # cruzó el semáforo en rojo
    max_speed_over_limit_mph: float = 0.0  # mayor exceso sobre el límite vigente
    sim_time_s: float = 0.0


def simulate(
    *,
    v0_mph: float,
    dist_m: float,
    grad_pct: float = 0.0,
    seq_start: int = 1000,
    max_s: float = 240.0,
    limit_next: Optional[tuple[float, float]] = None,
    station: bool = True,
    eff0_mph: float = 60.0,
    limit_signs: Optional[list[tuple[float, float]]] = None,
    signal_pos_m: Optional[float] = None,
    signal_green_at_s: Optional[float] = None,
) -> SimResult:
    """Aproximación a un andén (``dist_m`` al tablón) con elementos opcionales por el camino.

    ``limit_signs``: [(posición m desde el inicio, mph)] ordenados. ``signal_pos_m``: posición del
    semáforo desde el inicio; rojo hasta ``signal_green_at_s`` (siempre rojo si es ``None``).
    Con ``station=False`` el agente no recibe distancia de andén (solo cartel / señal).
    """
    prev_phys = get_active_physics()
    limit_state, release_state = LimitBrakeState(), BrakeReleaseState()
    v = v0_mph * MPH_TO_MS
    x = 0.0  # recorrido desde el inicio
    lever, target_lever, apply_at = 4, 4, 0.0
    ramp = 0.0
    t = 0.0
    seq = float(seq_start)
    commands: list[tuple[float, str, Optional[int]]] = []
    last_notch: Optional[int] = None
    last_change_t = -99.0
    changes = reversals = 0
    passed_red = False
    over = 0.0
    signs = sorted(limit_signs or [])
    logging.disable(logging.CRITICAL)
    try:
        while t < max_s:
            d = dist_m - x  # al tablón
            passed = [s for s in signs if s[0] - x <= SIGN_PASSED_M]
            ahead = [s for s in signs if s[0] - x > SIGN_PASSED_M]
            eff = passed[-1][1] if passed else eff0_mph
            if ahead:
                lim_mph, lim_dist = ahead[0][1], ahead[0][0] - x
            elif limit_next:
                lim_mph, lim_dist = limit_next[0], limit_next[1] - x
            else:
                lim_mph, lim_dist = None, None
            sig_red: Optional[bool] = None
            sig_dist: Optional[float] = None
            if signal_pos_m is not None and x < signal_pos_m:
                is_red = signal_green_at_s is None or t < signal_green_at_s
                sig_red, sig_dist = is_red, signal_pos_m - x
            elif signal_pos_m is not None and x >= signal_pos_m and sig_dist is None:
                if signal_green_at_s is None or t < signal_green_at_s:
                    passed_red = True
            brake_tb = 0.333 * (4 - lever) if lever < 4 else 0.0
            tick = {
                "seq": int(seq),
                "spd_mph": v / MPH_TO_MS,
                "eff_mph": eff,
                "lim_mph": lim_mph,
                "lim_dist_m": lim_dist,
                "lever": lever,
                "brake_cyl_bar": 1.03 + 1.4 * ramp,
                "grad_pct": grad_pct,
                "stn_dist_m": d if (station and d > 0) else None,
                "stn_fsm": None,
                "vehicle": VEHICLE,
                "signal_red": sig_red,
                "signal_dist_m": sig_dist,
            }
            snap = replace(tick_to_snap(tick), accel_ms2=None, train_brake=brake_tb, dyn_brake=brake_tb)
            dec = evaluate_p1_tick(
                limit_state,
                release_state,
                snap,
                learner=None,
                station_distance_m=d if (station and d > 0) else None,
                station_fsm=None,
            )
            cmd = dec.command
            if cmd is not None:
                if cmd.kind == "APPLY" and cmd.target_notch is not None:
                    n = int(cmd.target_notch)
                    if n != target_lever:
                        target_lever, apply_at = n, t + IPC_DELAY_S
                    if last_notch is not None and n != last_notch:
                        changes += 1
                        if t - last_change_t < 3.0:
                            reversals += 1
                    if last_notch is None or n != last_notch:
                        last_change_t = t
                    last_notch = n
                    commands.append((round(t, 2), "APPLY", n))
                elif cmd.kind in ("RELEASE", "COAST_THROTTLE"):
                    if target_lever != 4:
                        target_lever, apply_at = 4, t + IPC_DELAY_S
                    last_notch = None
                    commands.append((round(t, 2), cmd.kind, None))
            if t >= apply_at:
                lever = target_lever
            braking = lever < 4
            ramp += ((1.0 if braking else 0.0) - ramp) * DT_S / FILL_TAU_S
            decel = COAST_DECEL + (NOTCH_DECEL.get(lever, 0.0) * ramp if braking else 0.0)
            decel -= 9.81 * (-grad_pct) / 100.0  # bajada: la gravedad acelera
            v = max(0.0, v - decel * DT_S) if decel > 0 else v - decel * DT_S
            x += v * DT_S
            over = max(over, v / MPH_TO_MS - eff)
            t += DT_S
            seq += 1.0
            if v < 0.05 and t > 2.0:
                break
    finally:
        logging.disable(logging.NOTSET)
        set_active_physics(prev_phys)
    return SimResult(
        stop_dist_m=(dist_m - x) if station else 0.0,
        stopped=v < 0.05,
        notch_changes=changes,
        quick_reversals=reversals,
        commands=commands,
        signal_margin_m=(signal_pos_m - x) if signal_pos_m is not None else None,
        passed_red=passed_red,
        max_speed_over_limit_mph=over,
        sim_time_s=t,
    )
