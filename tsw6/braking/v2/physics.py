#!/usr/bin/env python3
"""
physics.py — Física única de frenado (Dastsc physics.ts + márgenes TSW6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tsw6.governor.governor_constants import (
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


@dataclass
class BrakePhysicsContext:
    """Entorno cinemático compartido por plan y consultas puntuales."""

    base_decel_ms2: float = DEFAULT_MAX_BRAKE_DECEL
    safety_margin: float = SAFETY_MARGIN
    coast_decel_ms2: float = COAST_DECEL_MS2
    brake_transition_s: float = BRAKE_TRANSITION_S
    gradient_pct: float = 0.0
    current_accel_ms2: Optional[float] = None


def gravity_acceleration_ms2(gradient_pct: float) -> float:
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


def decel_for_notch(
    fraction: float,
    base_decel: float,
    gradient_pct: float,
) -> float:
    grav = gravity_acceleration_ms2(gradient_pct)
    return max(base_decel * fraction + grav, 0.05)


def apply_zone_margin_m(speed_ms: float, apply_at_remaining_m: float) -> float:
    speed_based = speed_ms * 2.5
    remaining_based = apply_at_remaining_m * 0.12
    return min(
        APPLY_NOW_MARGIN_M,
        max(APPLY_NOW_MARGIN_MIN_M, speed_based, remaining_based),
    )


def is_in_apply_zone(dist_start: float, apply_zone_m: float) -> bool:
    if dist_start < 0:
        return True
    return dist_start <= apply_zone_m


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
