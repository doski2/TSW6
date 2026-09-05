#!/usr/bin/env python3
"""
physics.py — Física única de frenado (Dastsc physics.ts + márgenes TSW6).

Curva de servicio (ATO / RSSB, misma idea que Dastsc)::

    a_neta = a_freno + g * (pendiente/100)
             pendiente < 0 → bajada → menos decel → más metros

    s = (v² − u²) / (2 * a_neta)

``v`` velocidad actual, ``u`` objetivo (cartel o 0 en andén). Luego fill/reacción
(``brake_reaction_margin_m``) y ventana APPLY (``apply_zone_margin_m``: ~2,5 s
de marcha, cap 150 m). Eso es ``dist_start``: metros que aún faltan para aplicar.

A 60→50 mph con B1, ``s`` son cientos de metros, no millas. Un umbral fijo
«no frenar hasta 2 mi» rompe un 90→40; la curva no.

Capa aware vs act: el HUD puede mostrar el 50 a 4 km; APPLY/COAST solo cuando
``dist_start`` entra en la ventana (más un pre-coast de ~8 s). Overspeed
respecto al *siguiente* cartel no dispara freno lejos.

Gravedad al soltar: el fill (~2,5 s) sigue frenando y en bajada ``g`` empuja;
el RELEASE en pendiente se adelanta un poco en mph.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from tsw6v2.constants import (
    BRAKE_TRANSITION_S,
    COAST_DECEL_MS2,
    MAX_DECEL_MS2,
    P1_ACK_GUARD_S,
    P1_REACT_S,
    SAFETY_MARGIN,
)

# Dastsc physics.ts
MPH_TO_MS = 0.44704
G_MSS = 9.80665
DEFAULT_MAX_BRAKE_DECEL = MAX_DECEL_MS2
APPLY_NOW_MARGIN_M = 150.0
APPLY_NOW_MARGIN_MIN_M = 25.0
TARGET_CLUSTER_GAP_M = 350.0
DOWNHILL_LIMIT_GRADIENT_PCT = -0.3  # ‰ -3 en Dastsc
STATION_COAST_CUTOFF_M = 100.0
DEFAULT_BRAKE_FILL_S = 2.5
DEFAULT_REACTION_S = 1.5
PRESSURE_IDLE_MAX_BAR = 1.5
PRESSURE_BRAKING_MIN_BAR = 2.0
BRAKE_FILL_CLAMP = (0.8, 5.0)


@dataclass
class BrakePhysicsContext:
    """Entorno cinemático compartido por plan y consultas puntuales."""

    base_decel_ms2: float = DEFAULT_MAX_BRAKE_DECEL
    safety_margin: float = SAFETY_MARGIN
    coast_decel_ms2: float = COAST_DECEL_MS2
    brake_transition_s: float = BRAKE_TRANSITION_S
    gradient_pct: float = 0.0
    current_accel_ms2: Optional[float] = None
    # F-B (PLAN_V2 §2 paso 9): mass_factor en decel cuando HTTP masa cableado.
    # mass_factor: float = 1.0


def gravity_acceleration_ms2(gradient_pct: float) -> float:
    """Componente de g a lo largo de la vía (pendiente en %, no ‰)."""
    return G_MSS * (gradient_pct / 100.0)


def effective_decel_ms2(
    decel_ms2: float,
    gradient_pct: float,
    coast_floor: float = COAST_DECEL_MS2,
) -> float:
    return max(decel_ms2 + gravity_acceleration_ms2(gradient_pct), coast_floor)


def braking_distance_m(
    speed_ms: float,
    target_speed_ms: float,
    decel_ms2: float,
    *,
    ctx: Optional[BrakePhysicsContext] = None,
    apply_margin: bool = False,
) -> float:
    """
    Distancia cinemática v²/(2a).

    Con ``apply_margin=True`` añade margen TSW6 y transición tracción→freno
    (consultas FSM / GUI / emergencia). El planificador usa ``False``.
    """
    if decel_ms2 <= 0:
        return float("inf")
    if speed_ms <= target_speed_ms:
        return 0.0

    c = ctx or BrakePhysicsContext()
    effective = effective_decel_ms2(decel_ms2, c.gradient_pct, c.coast_decel_ms2)

    if c.current_accel_ms2 is not None and c.current_accel_ms2 > 0.0:
        t_trans = c.brake_transition_s
        v_peak = speed_ms + c.current_accel_ms2 * t_trans
        d_trans = speed_ms * t_trans + 0.5 * c.current_accel_ms2 * t_trans ** 2
        d_brake = (v_peak ** 2 - target_speed_ms ** 2) / (2.0 * effective)
        raw = d_trans + d_brake
    else:
        raw = (speed_ms ** 2 - target_speed_ms ** 2) / (2.0 * effective)

    if apply_margin:
        return raw * c.safety_margin
    return raw


def braking_distance_mph(
    speed_mph: float,
    target_speed_mph: float,
    *,
    decel_ms2: Optional[float] = None,
    ctx: Optional[BrakePhysicsContext] = None,
    apply_margin: bool = False,
) -> float:
    c = ctx or BrakePhysicsContext()
    decel = decel_ms2 if decel_ms2 is not None else c.base_decel_ms2
    return braking_distance_m(
        speed_mph * MPH_TO_MS,
        target_speed_mph * MPH_TO_MS,
        decel,
        ctx=c,
        apply_margin=apply_margin,
    )


def kinematic_horizon_m(
    speed_mph: float,
    target_speed_mph: float,
    *,
    decel_ms2: Optional[float] = None,
    ctx: Optional[BrakePhysicsContext] = None,
    apply_margin: bool = True,
    reaction_base_s: Optional[float] = None,
) -> float:
    """
    Distancia a la que hay que actuar: ``s = (v²−u²)/2a`` + reacción + zona apply.
    """
    speed_ms = speed_mph * MPH_TO_MS
    bd = braking_distance_mph(
        speed_mph,
        target_speed_mph,
        decel_ms2=decel_ms2,
        ctx=ctx,
        apply_margin=apply_margin,
    )
    if not math.isfinite(bd):
        return 0.0
    react = brake_reaction_margin_m(speed_ms, reaction_base_s=reaction_base_s)
    apply_at = bd + react
    return apply_at + apply_zone_margin_m(speed_ms, apply_at)


def decel_for_notch(
    fraction: float,
    base_decel: float,
    gradient_pct: float = 0.0,
) -> float:
    """Decel de servicio en **llano** (fracción × base).

    La pendiente entra **una sola vez** en ``braking_distance_m`` vía
    ``BrakePhysicsContext.gradient_pct``. No sumar ``g`` aquí: el learner ya
    devuelve a con grado, y duplicar g alarga/acorta ``s`` al doble.
    """
    del gradient_pct
    return max(base_decel * fraction, 0.05)


def brake_ctx_for_decel(
    *,
    gradient_pct: float,
    using_learned: bool,
    current_accel_ms2: Optional[float] = None,
    brake_transition_s: Optional[float] = None,
    base_decel_ms2: Optional[float] = None,
) -> BrakePhysicsContext:
    """ctx para ``s=(v²−u²)/2a``: fórmula → pendiente; aprendido → ya va en a."""
    return BrakePhysicsContext(
        gradient_pct=0.0 if using_learned else gradient_pct,
        current_accel_ms2=current_accel_ms2,
        brake_transition_s=(
            BRAKE_TRANSITION_S if brake_transition_s is None else brake_transition_s
        ),
        base_decel_ms2=(
            DEFAULT_MAX_BRAKE_DECEL if base_decel_ms2 is None else base_decel_ms2
        ),
    )


def apply_zone_margin_m(speed_ms: float, apply_at_remaining_m: float) -> float:
    speed_based = speed_ms * 2.5
    remaining_based = apply_at_remaining_m * 0.12
    return min(
        APPLY_NOW_MARGIN_M,
        max(APPLY_NOW_MARGIN_MIN_M, speed_based, remaining_based),
    )


def is_in_apply_zone(dist_start: float, apply_zone_m: float) -> bool:
    """Ventana simétrica ±zona (misma regla que ``should_emit_brake_command``)."""
    return -apply_zone_m <= dist_start <= apply_zone_m


def is_in_brake_action_window(
    dist_start: float,
    *,
    speed_mph: float,
    distance_to_target_m: Optional[float] = None,
    apply_at_remaining_m: Optional[float] = None,
) -> bool:
    """¿``dist_start`` está en la ventana de acción del plan (metros, vía física)?"""
    zone = brake_command_apply_zone_m(
        speed_mph=speed_mph,
        distance_to_target_m=distance_to_target_m,
        apply_at_remaining_m=apply_at_remaining_m,
        dist_start=dist_start,
    )
    return is_in_apply_zone(dist_start, zone)


def low_speed_reaction_scale(speed_ms: float, target_speed_ms: float) -> float:
    if speed_ms <= 0.5:
        return 1.0
    delta = max(0.0, speed_ms - target_speed_ms)
    ratio = delta / speed_ms
    return max(0.35, min(1.0, ratio / 0.4))


def reaction_margin_m(
    speed_ms: float,
    fill_time_s: float = DEFAULT_BRAKE_FILL_S,
    reaction_time_s: Optional[float] = None,
) -> float:
    if reaction_time_s is not None and reaction_time_s > 0:
        return speed_ms * reaction_time_s
    return speed_ms * min(4.0, DEFAULT_REACTION_S + fill_time_s)


def brake_reaction_margin_m(
    speed_ms: float,
    *,
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
    reaction_base_s: Optional[float] = None,
) -> float:
    """
  Margen de reacción con fill-time aprendido.

  - Sin ``reaction_base_s``: ``DEFAULT_REACTION_S + brake_fill_s`` (plan límite).
  - Con ``reaction_base_s``: base fija + delta si el tren tarda más que el fill por defecto
    (latch cartel / estación).
    """
    if reaction_base_s is not None:
        delta = max(0.0, brake_fill_s - DEFAULT_BRAKE_FILL_S)
        return reaction_margin_m(speed_ms, reaction_time_s=reaction_base_s + delta)
    return reaction_margin_m(speed_ms, fill_time_s=brake_fill_s)


def should_brake_for_target(
    speed_mph: float,
    target_mph: Optional[float],
    distance_m: Optional[float],
    *,
    ctx: Optional[BrakePhysicsContext] = None,
    react_s: float = 0.0,
    decel_ms2: Optional[float] = None,
) -> bool:
    """¿Hay que empezar a frenar ya? (sustituye ``should_brake_for_next``)."""
    if target_mph is None or distance_m is None:
        return False
    if target_mph >= speed_mph:
        return False
    react_m = speed_mph * MPH_TO_MS * react_s
    bd = braking_distance_mph(
        speed_mph,
        target_mph,
        decel_ms2=decel_ms2,
        ctx=ctx,
        apply_margin=True,
    )
    return distance_m <= bd + react_m


def should_coast_throttle_before_brake(
    speed_mph: float,
    target_mph: float,
    distance_m: float,
    *,
    ctx: Optional[BrakePhysicsContext] = None,
    react_s: float = P1_REACT_S + P1_ACK_GUARD_S,
    decel_ms2: Optional[float] = None,
) -> bool:
    """Perfil activo pero aún sin muesca — ¿soltar tracción ya?"""
    return should_brake_for_target(
        speed_mph,
        target_mph,
        distance_m,
        ctx=ctx,
        react_s=react_s,
        decel_ms2=decel_ms2,
    )


def brake_command_apply_zone_m(
    *,
    speed_mph: float,
    distance_to_target_m: Optional[float] = None,
    apply_at_remaining_m: Optional[float] = None,
    dist_start: Optional[float] = None,
) -> float:
    """
    Ventana de emisión de comando (misma fórmula que el planificador).

    Sustituye el antiguo umbral fijo de 60 m: escala con velocidad y distancia
    de frenado (``apply_zone_margin_m``).
    """
    speed_ms = speed_mph * MPH_TO_MS
    apply_at = _coherent_apply_at_remaining_m(
        distance_to_target_m=distance_to_target_m,
        apply_at_remaining_m=apply_at_remaining_m,
        dist_start=dist_start,
    )
    return apply_zone_margin_m(speed_ms, apply_at)


def speed_limit_pre_coast_horizon_m(
    *,
    speed_mph: float,
    distance_to_target_m: Optional[float] = None,
    apply_at_remaining_m: Optional[float] = None,
    dist_start: Optional[float] = None,
) -> float:
    """
    ``dist_start`` máximo para COAST (soltar tracción) antes del APPLY.

    ~8 s de marcha o 3× zona APPLY (≈200–270 m @ 60 mph). Lejos de eso el
    cartel siguiente solo se planifica (aware), no se toca el mando.
    """
    zone = brake_command_apply_zone_m(
        speed_mph=speed_mph,
        distance_to_target_m=distance_to_target_m,
        apply_at_remaining_m=apply_at_remaining_m,
        dist_start=dist_start,
    )
    speed_ms = speed_mph * MPH_TO_MS
    return max(zone * 3.0, speed_ms * 8.0, 80.0)


def _coherent_apply_at_remaining_m(
    *,
    distance_to_target_m: Optional[float],
    apply_at_remaining_m: Optional[float],
    dist_start: Optional[float],
) -> float:
    """``apply_at`` coherente con ``distance`` y ``dist_start`` si ambos existen."""
    derived: Optional[float] = None
    if distance_to_target_m is not None and dist_start is not None:
        derived = distance_to_target_m - dist_start
    if derived is not None:
        return max(0.0, derived)
    if apply_at_remaining_m is not None:
        return max(0.0, apply_at_remaining_m)
    return 0.0


def should_emit_brake_command(
    *,
    apply_now: bool,
    dist_start: float,
    speed_mph: float,
    distance_to_target_m: Optional[float] = None,
    apply_at_remaining_m: Optional[float] = None,
) -> bool:
    """
    ¿Emitir APPLY/COAST_THROTTLE?

    1. Ventana simétrica ±zona (velocidad + distancia de frenado).
    2. Tarde (``dist_start < 0``) pero aún dentro del envelope ``distance <= apply_at``.
    """
    del apply_now
    if is_in_brake_action_window(
        dist_start,
        speed_mph=speed_mph,
        distance_to_target_m=distance_to_target_m,
        apply_at_remaining_m=apply_at_remaining_m,
    ):
        return True
    apply_at = _coherent_apply_at_remaining_m(
        distance_to_target_m=distance_to_target_m,
        apply_at_remaining_m=apply_at_remaining_m,
        dist_start=dist_start,
    )
    if (
        dist_start < 0
        and distance_to_target_m is not None
        and distance_to_target_m <= apply_at
    ):
        return True
    return False
