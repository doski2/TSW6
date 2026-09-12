from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeReleaseState
from tsw6v2.decision import evaluate_p1_tick
from tsw6v2.limits import LimitBrakeState


def test_p1_tick_station_near_platform():
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 11.18,  # ~25 mph
            "lever_notch": 4,
            "dist_limit_cm": 500000.0,
            "next_limit_ms": 24.5872,
            "speed_limit_ms": 26.8224,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=80.0,
        limit_brake_enabled=True,
        station_brake_enabled=True,
    )
    assert decision.target_kind == "STATION"
    assert decision.command is not None
    assert decision.command.kind == "APPLY"


def test_no_phantom_limit_target_departure_session_221258() -> None:
    """Salida andén: cartel 35 lejos en WATCH no debe figurar como p1tgt."""
    snap = ProbeSnapshot(
        speed_ms=25.3,
        speed_limit_ms=26.8,
        gradient_pct=0.93,
        dist_limit_cm=399800.0,
        next_limit_ms=15.65,
        lever_notch=6,
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=8340.8,
        limit_brake_enabled=True,
        station_brake_enabled=True,
    )
    assert decision.reason == "no_plan"
    assert decision.target_kind == ""
    assert decision.command is None


def test_limit_release_after_downhill_hold_station_deferred_session_224046() -> None:
    """B1 tras HOLD_DH en zona 15: soltar aunque pick=None (andén lejos)."""
    state = LimitBrakeState()
    state.committed_handle = 3
    state.committed_phase = "B1"
    snap = ProbeSnapshot(
        speed_ms=6.46,  # ~14.4 mph
        speed_limit_ms=6.71,  # 15 mph vigente
        gradient_pct=-1.74,
        dist_limit_cm=100910.0,
        next_limit_ms=22.35,  # 50 mph
        lever_notch=3,
    )
    decision = evaluate_p1_tick(
        state,
        BrakeReleaseState(),
        snap,
        station_distance_m=5000.0,
        limit_brake_enabled=True,
        station_brake_enabled=True,
    )
    assert decision.reason == "release"
    assert decision.command is not None
    assert decision.command.kind == "RELEASE"
    assert state.committed_handle is None


def test_no_limit_release_while_station_braking():
    """Sesión 20260910T123139Z: latch 55 no debe soltar freno de andén @ ~212 m."""
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 20.43,  # ~45.7 mph
            "lever_notch": 1,
            "brake_cyl_bar": 2.8,
            "dist_limit_cm": 89500.0,
            "next_limit_ms": 20.1168,  # 45 mph
            "speed_limit_ms": 24.5872,  # zona 55
            "gradient_pct": -1.0,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=212.0,
        limit_brake_enabled=True,
        station_brake_enabled=True,
    )
    assert decision.target_kind == "STATION"
    assert decision.reason != "release"
    assert decision.command is None or decision.command.kind != "RELEASE"
