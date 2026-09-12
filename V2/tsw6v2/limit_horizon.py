"""Horizonte cinemático al cartel siguiente (inicio BRAKE_LIMIT)."""

from __future__ import annotations

from tsw6v2.limit_state import LIMIT_REACTION_S
from tsw6v2.physics import (
    DEFAULT_MAX_BRAKE_DECEL,
    brake_ctx_for_decel,
    kinematic_horizon_m,
)
from tsw6v2.plan import SERVICE_DECEL_FRAC_BY_HANDLE


def next_limit_brake_horizon_m(
    speed_mph: float,
    limit_mph: float,
    gradient_pct: float,
) -> float:
    """Distancia al cartel donde empieza BRAKE_LIMIT (s + reacción + zona)."""
    ctx = brake_ctx_for_decel(gradient_pct=gradient_pct, using_learned=False)
    b1_frac = SERVICE_DECEL_FRAC_BY_HANDLE[3]
    horizon = kinematic_horizon_m(
        speed_mph,
        limit_mph,
        decel_ms2=DEFAULT_MAX_BRAKE_DECEL * b1_frac,
        ctx=ctx,
        apply_margin=False,
        reaction_base_s=LIMIT_REACTION_S,
    )
    return horizon if horizon == horizon else 0.0


def within_next_brake_horizon(
    *,
    speed_mph: float,
    next_limit_mph: float,
    next_distance_m: float,
    gradient_pct: float,
) -> bool:
    """¿Dentro del horizonte BRAKE_LIMIT al cartel siguiente?"""
    horizon = next_limit_brake_horizon_m(speed_mph, next_limit_mph, gradient_pct)
    return next_distance_m <= horizon
