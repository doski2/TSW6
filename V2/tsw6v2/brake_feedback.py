"""Bucle cerrado: decel medida (accel_ms2) vs perfil → escalado de muesca."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from tsw6v2.brake_air import brake_decel_sample_ready
from tsw6v2.limit_notch import (
    _grade_escalation_allowed,
    _in_apply_window,
    _step_stronger,
    phase_for_handle,
)
from tsw6v2.limit_state import LimitBrakeState, PredictDecelFn
from tsw6v2.plan import notch_strength

# a_obs < ratio × a_pred durante N ticks → un escalón B1→B2→B3
DECEL_SHORTFALL_RATIO = 0.70
DECEL_MIN_PRED_MS2 = 0.15
DECEL_MIN_OBS_MS2 = 0.08
WEAK_DECEL_TICKS = 2


@dataclass(frozen=True)
class DecelFeedback:
    a_pred_ms2: Optional[float] = None
    a_obs_ms2: Optional[float] = None
    shortfall: bool = False
    escalated: bool = False


def observed_decel_ms2(accel_ms2: Optional[float]) -> Optional[float]:
    """Decel positiva (m/s²) si el probe reporta frenado."""
    if accel_ms2 is None:
        return None
    a = -float(accel_ms2)
    if a < DECEL_MIN_OBS_MS2:
        return None
    return a


def predicted_decel_ms2(
    predict_decel: Optional[PredictDecelFn],
    *,
    handle: int,
    speed_mph: float,
    gradient_pct: float,
) -> Optional[float]:
    if predict_decel is None:
        return None
    a = predict_decel(int(handle), float(speed_mph), float(gradient_pct))
    if a is None or a < DECEL_MIN_PRED_MS2:
        return None
    return float(a)


def measure_decel_feedback(
    *,
    predict_decel: Optional[PredictDecelFn],
    handle: int,
    speed_mph: float,
    gradient_pct: float,
    accel_ms2: Optional[float],
) -> DecelFeedback:
    a_pred = predicted_decel_ms2(
        predict_decel,
        handle=handle,
        speed_mph=speed_mph,
        gradient_pct=gradient_pct,
    )
    a_obs = observed_decel_ms2(accel_ms2)
    shortfall = (
        a_pred is not None
        and a_obs is not None
        and a_obs < DECEL_SHORTFALL_RATIO * a_pred
    )
    return DecelFeedback(
        a_pred_ms2=a_pred,
        a_obs_ms2=a_obs,
        shortfall=shortfall,
    )


def apply_weak_decel_feedback(
    state: LimitBrakeState,
    *,
    handle: int,
    phase: str,
    speed_mph: float,
    limit_mph: float,
    gradient_pct: float,
    accel_ms2: Optional[float],
    apply_now: bool,
    dist_start: float,
    apply_zone_m: float,
    predict_decel: Optional[PredictDecelFn],
    escalate_cap: Callable[[int, int], int] | None = None,
    lever: int | None = None,
    brake_cyl_bar: float | None = None,
) -> tuple[int, str, DecelFeedback]:
    """
    Si la decel real no alcanza el perfil con muesca comprometida, subir un escalón.

    Solo en ventana APPLY y con B1/B2 ya comprometidos (no en WATCH).
    """
    committed = state.committed_handle
    if committed is None:
        state.weak_decel_ticks = 0
        return handle, phase, DecelFeedback()

    in_window = _in_apply_window(
        apply_now=apply_now,
        dist_start=dist_start,
        apply_zone_m=apply_zone_m,
    )
    if not in_window:
        state.weak_decel_ticks = 0
        return handle, phase, DecelFeedback()

    if not brake_decel_sample_ready(
        handle=committed,
        lever=lever,
        brake_cyl_bar=brake_cyl_bar,
    ):
        state.weak_decel_ticks = 0
        return handle, phase, DecelFeedback()

    fb = measure_decel_feedback(
        predict_decel=predict_decel,
        handle=committed,
        speed_mph=speed_mph,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    )
    if fb.shortfall:
        state.weak_decel_ticks += 1
    else:
        state.weak_decel_ticks = 0
        return handle, phase, fb

    if state.weak_decel_ticks < WEAK_DECEL_TICKS:
        return handle, phase, fb

    if committed <= 1 or not _grade_escalation_allowed(
        gradient_pct, speed_mph, limit_mph
    ):
        return handle, phase, fb

    stepped, new_phase = _step_stronger(state, committed, escalate_cap=escalate_cap)
    state.weak_decel_ticks = 0
    if notch_strength(stepped) <= notch_strength(committed):
        return handle, phase, fb

    return (
        stepped,
        new_phase or phase_for_handle(stepped),
        DecelFeedback(
            a_pred_ms2=fb.a_pred_ms2,
            a_obs_ms2=fb.a_obs_ms2,
            shortfall=True,
            escalated=True,
        ),
    )
