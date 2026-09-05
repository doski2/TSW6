"""HOLD_DH — mantener límite vigente en bajada (solo misma zona; ver REGLAS_FRENOS_P1)."""

from __future__ import annotations

from typing import Optional

from tsw6v2.constants import passenger_ops_target_mph
from tsw6v2.physics import (
    DEFAULT_MAX_BRAKE_DECEL,
    DOWNHILL_LIMIT_GRADIENT_PCT,
    MPH_TO_MS,
    apply_zone_margin_m,
    brake_ctx_for_decel,
    kinematic_horizon_m,
)
from tsw6v2.plan import SERVICE_DECEL_FRAC_BY_HANDLE
from tsw6v2.target import (
    LIMIT_CONTAIN_ESCALATE_OVER_MPH,
    LIMIT_SCORING_MAX_OVER_MPH,
    BrakeTargetResult,
)
from tsw6v2.limit_notch import apply_notch_hysteresis
from tsw6v2.limit_state import LIMIT_REACTION_S, LimitBrakeState


def passenger_hold_target_mph(posted_limit_mph: float) -> float:
    """Techo operativo HOLD_DH (ej. cartel 60 → mantener ~59)."""
    return passenger_ops_target_mph(posted_limit_mph)


def _downhill_contain_trigger_over_mph(gradient_pct: float) -> float:
    """Repunte sobre techo operativo antes de B1 en HOLD_DH."""
    if gradient_pct <= -1.0:
        return 0.20
    if gradient_pct <= -0.6:
        return 0.28
    return 0.35


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
    HOLD_DH — solo si el cartel siguiente **no baja** (60→55 usa solo BRAKE_LIMIT).

    Techo operativo pasajeros: posted − 1 mph (60 → 59).
    """
    if gradient_pct >= DOWNHILL_LIMIT_GRADIENT_PCT:
        return None

    if (
        next_limit_mph is not None
        and next_limit_mph < posted_limit_mph - 0.5
    ):
        return None

    if next_limit_mph is not None and next_distance_m is not None:
        horizon = next_limit_brake_horizon_m(
            speed_mph, next_limit_mph, gradient_pct)
        if next_distance_m <= horizon:
            return None

    hold_target = passenger_hold_target_mph(posted_limit_mph)
    trigger = _downhill_contain_trigger_over_mph(gradient_pct)
    if speed_mph <= hold_target + trigger:
        return None

    over = speed_mph - hold_target
    speed_ms = speed_mph * MPH_TO_MS
    if over >= LIMIT_SCORING_MAX_OVER_MPH or over >= LIMIT_CONTAIN_ESCALATE_OVER_MPH:
        handle, phase = 2, "B2"
    else:
        handle, phase = 3, "B1"

    handle, phase = apply_notch_hysteresis(
        state,
        handle=handle,
        phase=phase,
        dist_start=0.0,
        apply_now=True,
        apply_zone_m=apply_zone_margin_m(speed_ms, 0.0),
        speed_mph=speed_mph,
        limit_mph=hold_target,
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
        detail=(
            f"Mantener bajada @{hold_target:.0f} mph "
            f"(posted {posted_limit_mph:.0f})"
        ),
    )
