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
