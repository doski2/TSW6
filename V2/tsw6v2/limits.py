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
from tsw6v2.brake_feedback import apply_weak_decel_feedback
from tsw6v2.learner import LearnerProfile
from tsw6v2.limit_containment import pick_downhill_containment
from tsw6v2.limit_notch import (
    apply_notch_hysteresis,
    downhill_defer_brake_commit,
    pick_weakest_sufficient_notch,
    _in_apply_window,
)
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
    learner: Optional[LearnerProfile] = None,
    lever: int | None = None,
    brake_cyl_bar: float | None = None,
) -> Optional[BrakeTargetResult]:
    """Planifica frenada al cartel. Re-latch si cambia el límite objetivo."""
    base = state.snapshot()
    dh_state = base.snapshot()
    next_state = base.snapshot()

    downhill_contain = None
    if posted_limit_mph is not None and limit_mph is not None and distance_m is not None:
        downhill_contain = pick_downhill_containment(
            dh_state,
            speed_mph=speed_mph,
            posted_limit_mph=posted_limit_mph,
            gradient_pct=gradient_pct,
            next_limit_mph=limit_mph,
            next_distance_m=distance_m,
        )

    next_r: Optional[BrakeTargetResult] = None
    if limit_mph is not None and distance_m is not None and distance_m > 0:
        next_r = _evaluate_next_limit_brake(
            next_state,
            speed_mph=speed_mph,
            limit_mph=limit_mph,
            distance_m=distance_m,
            gradient_pct=gradient_pct,
            accel_ms2=accel_ms2,
            base_decel=base_decel,
            predict_decel=predict_decel,
            brake_fill_s=brake_fill_s,
            escalate_cap=escalate_cap,
            current_posted_mph=posted_limit_mph,
            lever=lever,
            brake_cyl_bar=brake_cyl_bar,
        )

    def _commit_next() -> None:
        state.replace_from(next_state)
        if (
            learner is not None
            and next_r is not None
            and next_state.committed_handle is not None
            and _in_apply_window(
                apply_now=next_r.apply_now,
                dist_start=next_r.dist_start,
                apply_zone_m=apply_zone_margin_m(
                    speed_mph * MPH_TO_MS,
                    max(0.0, next_r.distance_m - next_r.dist_start),
                ),
            )
        ):
            learner.observe_brake_decel(
                handle=next_state.committed_handle,
                speed_mph=speed_mph,
                gradient_pct=gradient_pct,
                accel_ms2=accel_ms2,
                lever=lever,
                brake_cyl_bar=brake_cyl_bar,
            )

    def _commit_downhill() -> None:
        state.replace_from(dh_state)

    # H1: APPLY al cartel siguiente gana; HOLD_DH gana a WATCH del latch.
    if next_r is not None and next_r.apply_now:
        _commit_next()
        return next_r
    if downhill_contain is not None and (
        downhill_contain.downhill_hold or downhill_contain.apply_now
    ):
        # No dejar que WATCH (apply_now=false) bloquee HOLD_DH fuera del horizonte
        # (sesión 20260908T210357Z: 56–62 mph con P3 y sin COAST_PWR).
        _commit_downhill()
        return downhill_contain
    if next_r is not None:
        _commit_next()
        return next_r
    if downhill_contain is not None:
        _commit_downhill()
        return downhill_contain
    return None


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
    current_posted_mph: Optional[float] = None,
    lever: int | None = None,
    brake_cyl_bar: float | None = None,
) -> Optional[BrakeTargetResult]:
    """BRAKE_LIMIT — latch al cartel siguiente (techo operativo posted−1 mph)."""
    ops_target_mph = passenger_ops_target_mph(limit_mph)
    if speed_mph < ops_target_mph - 0.5:
        state.reset()
        return None

    if speed_mph <= ops_target_mph + LIMIT_COAST_BAND_MPH:
        state.reset()
        return None

    if limit_changed(state.last_limit_mph, limit_mph) or state.latch is None:
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
    defer_commit = (
        state.committed_handle is None
        and downhill_defer_brake_commit(
            speed_mph=speed_mph,
            ops_target_mph=latch.limit_mph,
            distance_m=distance_m,
            gradient_pct=gradient_pct,
            dist_start=dist_start,
            current_posted_mph=current_posted_mph,
            next_posted_mph=latch.posted_limit_mph,
        )
    )
    if defer_commit:
        apply_now = False
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
        gradient_pct=gradient_pct,
        defer_commit=defer_commit,
        escalate_cap=escalate_cap,
    )
    handle, phase, fb = apply_weak_decel_feedback(
        state,
        handle=handle,
        phase=phase,
        speed_mph=speed_mph,
        limit_mph=latch.limit_mph,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
        apply_now=apply_now,
        dist_start=dist_start,
        apply_zone_m=apply_zone_m,
        predict_decel=predict_decel,
        escalate_cap=escalate_cap,
        lever=lever,
        brake_cyl_bar=brake_cyl_bar,
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
        coast_trim_deferred=defer_commit,
        detail=(
            f"Límite {posted:.0f} mph → @{latch.limit_mph:.0f} "
            f"(latched @{latch.latched_speed_mph:.0f})"
        ),
        fb_a_pred_ms2=fb.a_pred_ms2,
        fb_a_obs_ms2=fb.a_obs_ms2,
        fb_shortfall=fb.shortfall,
        fb_escalated=fb.escalated,
    )
