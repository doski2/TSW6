from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeReleaseState
from tsw6v2.constants import EMERGENCY_BRAKE_HANDLE
from tsw6v2.decision import evaluate_p1_tick
from tsw6v2.limits import LimitBrakeState
from tsw6v2.p1_emergency import check_p1_emergency
from tsw6v2.planning_feed import format_planning_line, write_planning_snapshot


def test_check_p1_emergency_critico():
    cmd = check_p1_emergency(
        target_kind="STATION",
        speed_mph=40.0,
        urgent_dist_m=10.0,
    )
    assert cmd is not None
    assert cmd.target_notch == EMERGENCY_BRAKE_HANDLE


def test_p1_tick_emergency_before_station_plan():
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 17.88,  # ~40 mph
            "lever_notch": 4,
            "dist_limit_cm": 500000.0,
            "next_limit_ms": 26.8224,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=12.0,
    )
    assert decision.reason == "emergency"
    assert decision.command is not None
    assert decision.command.kind == "APPLY"


def test_write_planning_snapshot(tmp_path):
    path = tmp_path / "Planning.txt"
    ok = write_planning_snapshot(
        station_distance_m=842.0,
        station_name="Sutton Coldfield",
        path=path,
        min_interval_s=0.0,
    )
    assert ok
    text = path.read_text(encoding="utf-8").strip()
    assert "station_dist_m=842.0" in text
    assert "next_stop=Sutton_Coldfield" in text
    assert format_planning_line(station_distance_m=1.0) == "station_dist_m=1.0"
