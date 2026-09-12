from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeReleaseState
from tsw6v2.decision import evaluate_p1_tick
from tsw6v2.limits import LimitBrakeState
from tsw6v2.p1_policy import (
    pick_p1_brake_target,
    should_prefer_signal_over_limit,
    signal_behind_station,
)
from tsw6v2.signal_brake import evaluate_signal_brake
from tsw6v2.signal_plan import plan_brake_for_signal, should_suppress_signal_braking_for_departure
from tsw6v2.target import BrakeTargetResult


def _limit_watch(dist_start: float = 400.0) -> BrakeTargetResult:
    return BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=2000.0,
        target_speed_mph=20.0,
        handle_notch=3,
        phase="B1",
        dist_start=dist_start,
        apply_now=False,
        detail="Vigilar",
        downhill_hold=True,
    )


def test_plan_signal_far_red_starts_before_emergency_window():
    plan = plan_brake_for_signal(speed_mph=56.0, signal_distance_m=1040.0, gradient_pct=0.0)
    assert plan is not None
    assert plan.target_kind == "SIGNAL"
    upcoming = [s for s in plan.steps if s.dist_start > 0]
    assert upcoming
    # Planifica con margen (WATCH ~480 m) antes de emergencia (~180 m @ 56 mph).
    assert max(s.dist_start for s in upcoming) > 100.0


def test_evaluate_signal_watch_when_far():
    target = evaluate_signal_brake(
        speed_mph=56.0,
        signal_distance_m=1040.0,
        gradient_pct=0.0,
        throttle_notch=0,
    )
    assert target is not None
    assert target.target_kind == "SIGNAL"
    assert target.apply_now is False
    assert target.dist_start > 0


def test_evaluate_signal_apply_when_late():
    target = evaluate_signal_brake(
        speed_mph=34.0,
        signal_distance_m=162.0,
        gradient_pct=-1.0,
        throttle_notch=0,
    )
    assert target is not None
    assert target.apply_now is True


def test_no_signal_plan_when_stopped_at_departure():
    assert evaluate_signal_brake(
        speed_mph=0.0,
        signal_distance_m=2.0,
        throttle_notch=2,
        station_distance_m=14536.0,
    ) is None
    assert not should_suppress_signal_braking_for_departure(
        speed_mph=12.0,
        signal_distance_m=2.0,
        throttle_notch=2,
        station_distance_m=14536.0,
    )


def test_signal_behind_station():
    assert signal_behind_station(signal_dist_m=500.0, station_dist_m=200.0)
    assert not signal_behind_station(signal_dist_m=29.0, station_dist_m=31.0)


def test_signal_beats_hold_dh_deferred():
    signal = evaluate_signal_brake(
        speed_mph=11.6,
        signal_distance_m=29.2,
        gradient_pct=-1.0,
        throttle_notch=2,
        station_distance_m=31.3,
    )
    assert signal is not None
    picked = pick_p1_brake_target(
        speed_mph=11.6,
        limit_target=_limit_watch(dist_start=50.0),
        station_target=None,
        signal_target=signal,
        signal_dist_m=29.2,
        limit_mph=15.0,
        limit_dist_m=200.0,
        station_dist_m=31.3,
        effective_limit=15.0,
        gradient_pct=-1.0,
    )
    assert picked is not None
    assert picked.target_kind == "SIGNAL"


def test_should_prefer_signal_over_limit_always():
    signal = BrakeTargetResult(
        target_kind="SIGNAL",
        distance_m=500.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=200.0,
        apply_now=False,
        detail="",
    )
    assert should_prefer_signal_over_limit(signal, _limit_watch())


def test_p1_tick_coast_throttle_far_red_session_225433():
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 6594,
            "speed_ms": 25.0,
            "lever_notch": 6,
            "signal_red": True,
            "signal_dist_cm": 104000.0,
            "dist_limit_cm": 200000.0,
            "next_limit_ms": 8.94,
            "gradient_pct": 0.0,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=12070.0,
    )
    assert decision.target_kind == "SIGNAL"
    assert decision.reason in ("coast_throttle", "plan", "command_none")
    assert decision.command is not None or decision.reason == "command_none"


def test_p1_tick_signal_near_exit_beats_downhill_hold():
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 21710,
            "speed_ms": 5.19,
            "lever_notch": 6,
            "signal_red": True,
            "signal_dist_cm": 2920.0,
            "dist_limit_cm": 50000.0,
            "next_limit_ms": 6.7,
            "gradient_pct": -1.0,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=31.3,
    )
    assert decision.target_kind == "SIGNAL"
    assert decision.reason in ("coast_throttle", "plan")


def test_p1_tick_no_signal_plan_at_departure():
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 0.0,
            "lever_notch": 6,
            "signal_red": True,
            "signal_dist_cm": 200.0,
            "dist_limit_cm": 18410.0,
            "next_limit_ms": 6.7,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=14536.0,
    )
    assert decision.target_kind != "SIGNAL"
