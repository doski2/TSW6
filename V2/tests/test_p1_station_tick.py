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


def test_orphan_release_b2_after_zone_change_session_095417() -> None:
    """B2 heredado tras 15→30: soltar aunque RELEASE al 50 no aplica (spd ~15 mph)."""
    state = LimitBrakeState()
    state.committed_handle = 2
    state.committed_phase = "B2"
    snap = ProbeSnapshot(
        speed_ms=6.97,  # ~15.6 mph
        speed_limit_ms=13.41,  # 30 mph vigente
        gradient_pct=-1.74,
        dist_limit_cm=99720.0,
        next_limit_ms=22.35,  # 50 mph
        lever_notch=2,
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


def _snap_15_to_50_downhill(speed_ms: float, lever_notch: int) -> ProbeSnapshot:
    return ProbeSnapshot(
        speed_ms=speed_ms,
        lever_notch=lever_notch,
        gradient_pct=-1.74,
        dist_limit_cm=100220.0,
        next_limit_ms=22.35,
        speed_limit_ms=6.71,  # 15 mph
    )


def test_latch_blocks_rehold_after_zone_release_session_095417() -> None:
    """Tras RELEASE eff_floor @14.9, no re-HOLD_DH @15.5 (sesión 095417Z tick 2873)."""
    state = LimitBrakeState()
    release = BrakeReleaseState()
    stn_m = 5000.0
    evaluate_p1_tick(
        state,
        release,
        _snap_15_to_50_downhill(6.67, 3),
        station_distance_m=stn_m,
        limit_brake_enabled=True,
        station_brake_enabled=True,
    )
    released = evaluate_p1_tick(
        state,
        release,
        _snap_15_to_50_downhill(6.68, 3),
        station_distance_m=stn_m,
        limit_brake_enabled=True,
        station_brake_enabled=True,
    )
    assert released.command is not None
    assert released.command.kind == "RELEASE"

    decision = evaluate_p1_tick(
        state,
        release,
        _snap_15_to_50_downhill(6.93, 3),  # ~15.5 mph
        station_distance_m=stn_m,
        limit_brake_enabled=True,
        station_brake_enabled=True,
    )
    assert decision.reason != "downhill_hold"
    assert decision.command is None or decision.command.kind != "APPLY"


def test_station_watch_overlay_hold_dh_zone15_session_173809() -> None:
    """STATION WATCH no debe bloquear HOLD_DH en zona 15 (21 mph, 173809Z)."""
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 9.39,  # ~21 mph
            "lever_notch": 4,
            "brake_cyl_bar": 1.0,
            "gradient_pct": -1.0,
            "speed_limit_ms": 6.7056,  # 15 mph vigente
            "dist_limit_cm": 28300.0,
            "next_limit_ms": 22.352,  # 50 mph
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=289.6,
        limit_brake_enabled=True,
        station_brake_enabled=True,
    )
    assert decision.target_kind == "STATION"
    assert decision.command is not None
    assert decision.command.kind == "APPLY"
    assert decision.reason == "downhill_hold"


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
