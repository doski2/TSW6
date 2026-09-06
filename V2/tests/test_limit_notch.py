from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.limit_notch import (
    apply_notch_hysteresis,
    pick_weakest_sufficient_notch,
)
from tsw6v2.limit_state import LimitBrakeState, latch_limit_target
from tsw6v2.limits import evaluate_limit_brake


def _latched_state(*, speed_mph: float, distance_m: float) -> LimitBrakeState:
    state = LimitBrakeState()
    latch_limit_target(
        state,
        posted_limit_mph=55.0,
        distance_m=distance_m,
        speed_mph=speed_mph,
        gradient_pct=-1.0,
        accel_ms2=None,
        base_decel=1.071,
        predict_decel=None,
    )
    return state


def test_pick_weakest_uses_raw_kinematic_distance() -> None:
    state = _latched_state(speed_mph=59.8, distance_m=400.0)
    latch = state.latch
    assert latch is not None
    handle, phase, dist_start, apply_now = pick_weakest_sufficient_notch(
        speed_mph=59.8,
        distance_m=400.0,
        latch=latch,
    )
    assert handle == 3
    assert phase == "B1"
    assert not apply_now
    assert dist_start > 70.0


def test_hysteresis_escalates_on_overspeed_when_pick_still_b1() -> None:
    state = LimitBrakeState()
    state.committed_handle = 3
    state.committed_phase = "B1"
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
    assert phase == "B2"


def test_hysteresis_stays_b1_downhill_until_near_ops_target() -> None:
    state = LimitBrakeState()
    state.committed_handle = 3
    state.committed_phase = "B1"
    handle, phase = apply_notch_hysteresis(
        state,
        handle=3,
        phase="B1",
        dist_start=20.0,
        apply_now=True,
        apply_zone_m=50.0,
        speed_mph=59.5,
        limit_mph=54.0,
        gradient_pct=-1.0,
    )
    assert handle == 3
    assert phase == "B1"


def test_hysteresis_steps_b1_to_b2_when_requested() -> None:
    state = LimitBrakeState()
    state.committed_handle = 3
    state.committed_phase = "B1"
    handle, phase = apply_notch_hysteresis(
        state,
        handle=2,
        phase="B2",
        dist_start=10.0,
        apply_now=True,
        apply_zone_m=50.0,
        speed_mph=58.0,
        limit_mph=54.0,
    )
    assert handle == 2
    assert phase == "B2"


def test_evaluate_limit_brake_escalates_after_b1_committed() -> None:
    state = _latched_state(speed_mph=55.5, distance_m=120.0)
    state.committed_handle = 3
    state.committed_phase = "B1"

    second = evaluate_limit_brake(
        state,
        speed_mph=55.3,
        limit_mph=55.0,
        distance_m=120.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert second is not None
    assert second.apply_now
    assert second.handle_notch == 2
    assert second.phase == "B2"


def test_evaluate_limit_brake_defers_apply_while_legal_in_current_zone() -> None:
    state = _latched_state(speed_mph=59.8, distance_m=340.0)
    result = evaluate_limit_brake(
        state,
        speed_mph=59.8,
        limit_mph=55.0,
        distance_m=340.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert result is not None
    assert not result.apply_now
    assert result.handle_notch == 3
