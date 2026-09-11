"""HOLD_DH y contención bajada — ver REGLAS_FRENOS_P1.md."""

from __future__ import annotations

from typing import Optional

from tsw6v2.constants import (
    posted_zone_hold_ceiling_mph,
    posted_zone_coast_floor_mph,
)
from tsw6v2.planning import is_ascending_limit_exit, is_descending_limit_zone
from tsw6v2.limit_notch import apply_notch_hysteresis, phase_for_handle
from tsw6v2.limit_state import LIMIT_REACTION_S, LimitBrakeState
from tsw6v2.physics import (
    DEFAULT_MAX_BRAKE_DECEL,
    MPH_TO_MS,
    apply_zone_margin_m,
    brake_ctx_for_decel,
    is_downhill_gradient,
    kinematic_horizon_m,
)
from tsw6v2.plan import SERVICE_DECEL_FRAC_BY_HANDLE
from tsw6v2.target import BrakeTargetResult


def _hold_detail(posted_limit_mph: float, hold_target: float) -> str:
    return (
        f"Mantener bajada @{hold_target:.1f} mph "
        f"(posted {posted_limit_mph:.0f})"
    )


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


def _within_next_brake_horizon(
    *,
    speed_mph: float,
    next_limit_mph: float,
    next_distance_m: float,
    gradient_pct: float,
) -> bool:
    horizon = next_limit_brake_horizon_m(speed_mph, next_limit_mph, gradient_pct)
    return next_distance_m <= horizon


def _build_downhill_hold_result(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    hold_target: float,
    gradient_pct: float,
    next_distance_m: Optional[float],
    detail: str,
) -> BrakeTargetResult:
    speed_ms = speed_mph * MPH_TO_MS
    start_handle = 3
    handle, phase = apply_notch_hysteresis(
        state,
        handle=start_handle,
        phase=phase_for_handle(start_handle),
        dist_start=0.0,
        apply_now=True,
        apply_zone_m=apply_zone_margin_m(speed_ms, 0.0),
        speed_mph=speed_mph,
        limit_mph=hold_target,
        gradient_pct=gradient_pct,
    )
    return BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=next_distance_m if next_distance_m is not None else 0.0,
        target_speed_mph=hold_target,
        handle_notch=handle,
        phase=phase,
        dist_start=0.0,
        apply_now=True,
        downhill_hold=True,
        detail=detail,
    )


def _hold_if_over_zone_ceiling(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    posted_limit_mph: float,
    gradient_pct: float,
    next_distance_m: Optional[float],
) -> Optional[BrakeTargetResult]:
    hold_target = posted_zone_hold_ceiling_mph(posted_limit_mph, gradient_pct)
    if speed_mph <= hold_target:
        return None
    return _build_downhill_hold_result(
        state,
        speed_mph=speed_mph,
        hold_target=hold_target,
        gradient_pct=gradient_pct,
        next_distance_m=next_distance_m,
        detail=_hold_detail(posted_limit_mph, hold_target),
    )


def _defer_zone_contain_for_next_horizon(
    *,
    speed_mph: float,
    posted_limit_mph: float,
    next_limit_mph: Optional[float],
    next_distance_m: Optional[float],
    gradient_pct: float,
) -> bool:
    """Dentro del horizonte BRAKE_LIMIT al next: no HOLD zona vigente."""
    return (
        next_limit_mph is not None
        and next_distance_m is not None
        and is_descending_limit_zone(posted_limit_mph, next_limit_mph)
        and _within_next_brake_horizon(
            speed_mph=speed_mph,
            next_limit_mph=next_limit_mph,
            next_distance_m=next_distance_m,
            gradient_pct=gradient_pct,
        )
    )


def try_current_zone_contain(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    posted_limit_mph: float,
    gradient_pct: float,
    next_limit_mph: Optional[float] = None,
    next_distance_m: Optional[float] = None,
) -> Optional[BrakeTargetResult]:
    """
    Techo zona vigente lejos del next (60.5 @ +0.3 %%, 60.2 @ −1 %%).

    60→55/50 lejos: B1 suave si superas posted+margen; el techo depende de la
    pendiente vía ``posted_zone_hold_ceiling_mph`` (sesiones 204031Z, 203100Z).
    """
    if is_ascending_limit_exit(posted_limit_mph, next_limit_mph):
        return None
    if _defer_zone_contain_for_next_horizon(
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        next_limit_mph=next_limit_mph,
        next_distance_m=next_distance_m,
        gradient_pct=gradient_pct,
    ):
        return None
    return _hold_if_over_zone_ceiling(
        state,
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        gradient_pct=gradient_pct,
        next_distance_m=next_distance_m,
    )


def try_posted_downhill_hold(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    posted_limit_mph: float,
    gradient_pct: float,
    next_limit_mph: Optional[float] = None,
    next_distance_m: Optional[float] = None,
) -> Optional[BrakeTargetResult]:
    """
    HOLD_DH — cartel siguiente no baja (60→60).

    En 60→55 lejos del cartel usar ``try_current_zone_contain``.
    """
    if not is_downhill_gradient(gradient_pct):
        return None

    if is_descending_limit_zone(posted_limit_mph, next_limit_mph):
        return None

    if is_ascending_limit_exit(posted_limit_mph, next_limit_mph):
        return None

    if next_limit_mph is not None and next_distance_m is not None:
        if _within_next_brake_horizon(
            speed_mph=speed_mph,
            next_limit_mph=next_limit_mph,
            next_distance_m=next_distance_m,
            gradient_pct=gradient_pct,
        ):
            return None

    return _hold_if_over_zone_ceiling(
        state,
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        gradient_pct=gradient_pct,
        next_distance_m=next_distance_m,
    )


def pick_downhill_containment(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    posted_limit_mph: float,
    gradient_pct: float,
    next_limit_mph: Optional[float] = None,
    next_distance_m: Optional[float] = None,
) -> Optional[BrakeTargetResult]:
    """Zona vigente lejos del next o HOLD_DH (60→60 en bajada)."""
    zone = try_current_zone_contain(
        state,
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        gradient_pct=gradient_pct,
        next_limit_mph=next_limit_mph,
        next_distance_m=next_distance_m,
    )
    if zone is not None:
        return zone
    return try_posted_downhill_hold(
        state,
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        gradient_pct=gradient_pct,
        next_limit_mph=next_limit_mph,
        next_distance_m=next_distance_m,
    )


def downhill_brake_release_floor_mph(
    *,
    speed_mph: float,
    effective_limit: float,
    next_limit_mph: float,
    distance_next_m: float,
    gradient_pct: float,
    release_over_mph: float,
) -> Optional[float]:
    """
    Suelo RELEASE en bajada (ops + 0.5).

    - Acercándose al cartel next (55→45): soltar ~44.5, también en horizonte.
    - Zona vigente lejos del next (60→55): coast ~59.5.
    - En banda zona vigente tras frenar (45 @ ~44.5): no seguir con B1 hasta 40.
    """
    if not is_downhill_gradient(gradient_pct):
        return None
    if is_ascending_limit_exit(effective_limit, next_limit_mph):
        return None

    next_floor = posted_zone_coast_floor_mph(next_limit_mph)
    if speed_mph <= next_floor + release_over_mph:
        return next_floor

    in_horizon = _within_next_brake_horizon(
        speed_mph=speed_mph,
        next_limit_mph=next_limit_mph,
        next_distance_m=distance_next_m,
        gradient_pct=gradient_pct,
    )
    if not in_horizon:
        eff_floor = posted_zone_coast_floor_mph(effective_limit)
        ceiling = posted_zone_hold_ceiling_mph(effective_limit, gradient_pct)
        if eff_floor <= speed_mph <= ceiling:
            return eff_floor
        if eff_floor - 1.0 <= speed_mph <= eff_floor + release_over_mph:
            return eff_floor

    return None
