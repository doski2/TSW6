from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.brake_feedback import (
    apply_weak_decel_feedback,
    measure_decel_feedback,
    observed_decel_ms2,
)
from tsw6v2.limit_state import LimitBrakeState, latch_limit_target
from tsw6v2.limits import evaluate_limit_brake


def _predict_b1(_h: int, _spd: float, _grad: float) -> float:
    return 0.50


def test_observed_decel_from_accel() -> None:
    assert observed_decel_ms2(-0.42) == 0.42
    assert observed_decel_ms2(0.1) is None
    assert observed_decel_ms2(None) is None


def test_measure_shortfall_when_weak_brake() -> None:
    fb = measure_decel_feedback(
        predict_decel=_predict_b1,
        handle=3,
        speed_mph=55.0,
        gradient_pct=-1.0,
        accel_ms2=-0.20,
    )
    assert fb.a_pred_ms2 == 0.50
    assert fb.a_obs_ms2 == 0.20
    assert fb.shortfall is True


def test_escalate_after_two_weak_ticks() -> None:
    state = LimitBrakeState()
    state.committed_handle = 3
    state.committed_phase = "B1"
    kwargs = {
        "handle": 3,
        "phase": "B1",
        "speed_mph": 55.0,
        "limit_mph": 54.0,
        "gradient_pct": -1.0,
        "accel_ms2": -0.20,
        "apply_now": True,
        "dist_start": 10.0,
        "apply_zone_m": 50.0,
        "predict_decel": _predict_b1,
        "escalate_cap": None,
        "lever": 3,
        "brake_cyl_bar": 2.8,
    }
    h1, p1, fb1 = apply_weak_decel_feedback(state, **kwargs)
    assert h1 == 3
    assert not fb1.escalated
    assert state.weak_decel_ticks == 1

    h2, p2, fb2 = apply_weak_decel_feedback(state, **kwargs)
    assert h2 == 2
    assert p2 == "B2"
    assert fb2.escalated is True
    assert state.committed_handle == 2


def test_evaluate_limit_brake_escalates_on_weak_observed_decel() -> None:
    state = LimitBrakeState()
    latch_limit_target(
        state,
        posted_limit_mph=55.0,
        distance_m=120.0,
        speed_mph=55.5,
        gradient_pct=-1.0,
        accel_ms2=None,
        base_decel=1.071,
        predict_decel=_predict_b1,
    )
    state.committed_handle = 3
    state.committed_phase = "B1"

    first = evaluate_limit_brake(
        state,
        speed_mph=54.6,
        limit_mph=55.0,
        distance_m=80.0,
        gradient_pct=-1.0,
        accel_ms2=-0.18,
        predict_decel=_predict_b1,
        posted_limit_mph=60.0,
        lever=3,
        brake_cyl_bar=2.8,
    )
    assert first is not None
    assert first.handle_notch == 3
    assert first.fb_shortfall is True

    second = evaluate_limit_brake(
        state,
        speed_mph=54.5,
        limit_mph=55.0,
        distance_m=78.0,
        gradient_pct=-1.0,
        accel_ms2=-0.18,
        predict_decel=_predict_b1,
        posted_limit_mph=60.0,
        lever=3,
        brake_cyl_bar=2.8,
    )
    assert second is not None
    assert second.handle_notch == 2
    assert second.phase == "B2"
    assert second.fb_escalated is True


def test_no_double_escalation_hysteresis_then_feedback() -> None:
    """Un escalón por tick: histéresis por overspeed no abre paso a feedback."""
    from tsw6v2.limit_notch import apply_notch_hysteresis

    state = LimitBrakeState()
    state.committed_handle = 3
    state.committed_phase = "B1"
    state.weak_decel_ticks = 2

    handle, phase = apply_notch_hysteresis(
        state,
        handle=3,
        phase="B1",
        dist_start=20.0,
        apply_now=True,
        apply_zone_m=50.0,
        speed_mph=55.5,
        limit_mph=54.0,
        gradient_pct=-1.0,
    )
    assert handle == 2
    assert state.weak_decel_ticks == 0

    h2, p2, fb = apply_weak_decel_feedback(
        state,
        handle=handle,
        phase=phase,
        speed_mph=55.5,
        limit_mph=54.0,
        gradient_pct=-1.0,
        accel_ms2=-0.18,
        apply_now=True,
        dist_start=20.0,
        apply_zone_m=50.0,
        predict_decel=_predict_b1,
        escalate_cap=None,
        lever=3,
        brake_cyl_bar=2.8,
    )
    assert h2 == 2
    assert not fb.escalated


def test_feedback_ignores_low_pressure_transient() -> None:
    state = LimitBrakeState()
    state.committed_handle = 3
    state.weak_decel_ticks = 1
    h, p, fb = apply_weak_decel_feedback(
        state,
        handle=3,
        phase="B1",
        speed_mph=55.0,
        limit_mph=54.0,
        gradient_pct=-1.0,
        accel_ms2=-0.15,
        apply_now=True,
        dist_start=10.0,
        apply_zone_m=50.0,
        predict_decel=_predict_b1,
        lever=3,
        brake_cyl_bar=1.2,
    )
    assert h == 3
    assert fb.a_obs_ms2 is None
    assert state.weak_decel_ticks == 0


def test_no_shortfall_when_observed_meets_profile() -> None:
    fb = measure_decel_feedback(
        predict_decel=_predict_b1,
        handle=3,
        speed_mph=55.0,
        gradient_pct=-1.0,
        accel_ms2=-0.40,
    )
    assert fb.shortfall is False
