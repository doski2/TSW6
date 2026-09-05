#!/usr/bin/env python3
"""
Planificador P1 cartel — **diseño V2 desde cero** (no port v1).

Especificación: [REGLAS_FRENOS_P1.md](../../docs/v2/REGLAS_FRENOS_P1.md).

Lógica transitoria (hasta `limit_planner.py`):
  limit_state.py      — latch BRAKE_LIMIT
  limit_notch.py      — escalón B1→B3
  limit_containment.py — HOLD_DH (Fase 1) + horizonte BRAKE_LIMIT
  limits.py           — fachada (HOLD_DH + latch)
"""

from __future__ import annotations

from typing import Callable, Optional

from tsw6v2.constants import passenger_ops_target_mph
from tsw6v2.limit_containment import try_posted_downhill_hold
from tsw6v2.limit_notch import apply_notch_hysteresis, pick_weakest_sufficient_notch
from tsw6v2.limit_state import (
    LimitBrakeLatch,
    LimitBrakeState,
    PredictDecelFn,
    latch_limit_target,
    limit_changed,
    refresh_latch_physics,
)
from tsw6v2.physics import (
    DEFAULT_BRAKE_FILL_S,
    DEFAULT_MAX_BRAKE_DECEL,
    MPH_TO_MS,
    apply_zone_margin_m,
)
from tsw6v2.target import LIMIT_COAST_BAND_MPH, BrakeTargetResult

__all__ = [
    "LimitBrakeLatch",
    "LimitBrakeState",
    "PredictDecelFn",
    "evaluate_limit_brake",
]


def evaluate_limit_brake(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    limit_mph: Optional[float],
    distance_m: Optional[float],
    gradient_pct: float = 0.0,
    accel_ms2: Optional[float] = None,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
    predict_decel: Optional[PredictDecelFn] = None,
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
    posted_limit_mph: Optional[float] = None,
    escalate_cap: Callable[[int, int], int] | None = None,
) -> Optional[BrakeTargetResult]:
    """Planifica frenada al cartel. Re-latch si cambia el límite objetivo."""
    posted_hold = None
    if posted_limit_mph is not None and limit_mph is not None and distance_m is not None:
        posted_hold = try_posted_downhill_hold(
            state,
            speed_mph=speed_mph,
            posted_limit_mph=posted_limit_mph,
            gradient_pct=gradient_pct,
            next_limit_mph=limit_mph,
            next_distance_m=distance_m,
        )

    next_r: Optional[BrakeTargetResult] = None
    if limit_mph is not None and distance_m is not None and distance_m > 0:
        next_r = _evaluate_next_limit_brake(
            state,
            speed_mph=speed_mph,
            limit_mph=limit_mph,
            distance_m=distance_m,
            gradient_pct=gradient_pct,
            accel_ms2=accel_ms2,
            base_decel=base_decel,
            predict_decel=predict_decel,
            brake_fill_s=brake_fill_s,
            escalate_cap=escalate_cap,
        )

    # H1: dentro del horizonte del cartel siguiente → plan latch gana.
    if next_r is not None and next_r.apply_now:
        return next_r
    if posted_hold is not None:
        return posted_hold
    return next_r


def _evaluate_next_limit_brake(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    limit_mph: float,
    distance_m: float,
    gradient_pct: float,
    accel_ms2: Optional[float],
    base_decel: float,
    predict_decel: Optional[PredictDecelFn],
    brake_fill_s: float,
    escalate_cap: Callable[[int, int], int] | None = None,
) -> Optional[BrakeTargetResult]:
    """BRAKE_LIMIT — latch al cartel siguiente (techo operativo posted−1 mph)."""
    ops_target_mph = passenger_ops_target_mph(limit_mph)
    if speed_mph < ops_target_mph - 0.5:
        state.reset()
        return None

    if speed_mph <= ops_target_mph + LIMIT_COAST_BAND_MPH:
        state.reset()
        return None

    if limit_changed(state.last_limit_mph, limit_mph):
        latch_limit_target(
            state,
            posted_limit_mph=limit_mph,
            distance_m=distance_m,
            speed_mph=speed_mph,
            gradient_pct=gradient_pct,
            accel_ms2=accel_ms2,
            base_decel=base_decel,
            predict_decel=predict_decel,
            brake_fill_s=brake_fill_s,
        )
    elif state.latch is None:
        latch_limit_target(
            state,
            posted_limit_mph=limit_mph,
            distance_m=distance_m,
            speed_mph=speed_mph,
            gradient_pct=gradient_pct,
            accel_ms2=accel_ms2,
            base_decel=base_decel,
            predict_decel=predict_decel,
            brake_fill_s=brake_fill_s,
        )

    latch = state.latch
    if latch is None:
        return None

    refresh_latch_physics(
        latch,
        speed_mph=speed_mph,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
        base_decel=base_decel,
        predict_decel=predict_decel,
        brake_fill_s=brake_fill_s,
    )

    handle, phase, dist_start, apply_now = pick_weakest_sufficient_notch(
        speed_mph=speed_mph,
        distance_m=distance_m,
        latch=latch,
    )
    apply_at = max(0.0, distance_m - dist_start)
    apply_zone_m = apply_zone_margin_m(speed_mph * MPH_TO_MS, apply_at)
    handle, phase = apply_notch_hysteresis(
        state,
        handle=handle,
        phase=phase,
        dist_start=dist_start,
        apply_now=apply_now,
        apply_zone_m=apply_zone_m,
        speed_mph=speed_mph,
        limit_mph=latch.limit_mph,
        escalate_cap=escalate_cap,
    )

    posted = latch.posted_limit_mph
    return BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=distance_m,
        target_speed_mph=latch.limit_mph,
        handle_notch=handle,
        phase=phase,
        dist_start=dist_start,
        apply_now=apply_now,
        detail=(
            f"Límite {posted:.0f} mph → @{latch.limit_mph:.0f} "
            f"(latched @{latch.latched_speed_mph:.0f})"
        ),
    )
