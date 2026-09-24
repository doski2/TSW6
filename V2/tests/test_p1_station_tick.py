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


def test_downhill_hold_after_departure_creep_session_213920() -> None:
    """Tras creep salida (>11 mph): cartel 10 debe poder frenar (213920Z)."""
    snap = ProbeSnapshot(
        speed_ms=5.6,  # ~12.5 mph
        speed_limit_ms=4.47,  # 10 mph vigente
        gradient_pct=-0.35,
        dist_limit_cm=121600.0,
        next_limit_ms=13.4112,  # 30 mph
        lever_notch=4,
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=24141.8,
        limit_brake_enabled=True,
        station_brake_enabled=True,
        station_fsm="DEPARTING",
    )
    assert decision.reason == "downhill_hold"
    assert decision.command is not None
    assert decision.command.kind == "APPLY"


def test_departure_coast_watch_over_zone_ceiling_session_182951() -> None:
    """Zona 10 en creep salida: coast watch extendido, no no_plan ni B1 (182951Z)."""
    snap = ProbeSnapshot(
        speed_ms=10.5 / 2.237,
        speed_limit_ms=10.0 / 2.237,
        gradient_pct=-0.35,
        dist_limit_cm=4630.0,
        next_limit_ms=30.0 / 2.237,
        lever_notch=4,
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=None,
        limit_brake_enabled=True,
        station_brake_enabled=True,
        station_fsm="DEPARTING",
    )
    assert decision.reason != "no_plan"
    assert decision.reason != "downhill_hold"
    assert decision.command is None or decision.command.kind != "APPLY"


def test_departure_no_plan_gap_at_zone_ceiling_session_182951() -> None:
    """Tick 1326: spd == techo HOLD @10.2 — sin hueco no_plan."""
    snap = ProbeSnapshot(
        speed_ms=10.2 / 2.237,
        speed_limit_ms=10.0 / 2.237,
        gradient_pct=-1.72,
        dist_limit_cm=4630.0,
        next_limit_ms=30.0 / 2.237,
        lever_notch=4,
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=None,
        limit_brake_enabled=True,
        station_brake_enabled=True,
        station_fsm="DEPARTING",
    )
    assert decision.reason != "no_plan"


def test_no_downhill_hold_while_departing_session_223013() -> None:
    """Salida ~10 mph: HOLD_DH no debe frenar (223013Z tick 3071)."""
    snap = ProbeSnapshot(
        speed_ms=4.58,  # ~10.25 mph
        speed_limit_ms=4.47,  # 10 mph vigente
        gradient_pct=-1.74,
        dist_limit_cm=5905.0,
        next_limit_ms=6.71,  # 15 mph
        lever_notch=4,
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=24025.9,
        limit_brake_enabled=True,
        station_brake_enabled=True,
        station_fsm="DEPARTING",
    )
    assert decision.reason != "downhill_hold"
    assert decision.command is None or decision.command.kind != "APPLY"


def test_departing_release_from_decision_session_223013() -> None:
    """DEPARTING+B1: un solo RELEASE vía decision (no dwell duplicado)."""
    snap = ProbeSnapshot(
        speed_ms=0.0,
        speed_limit_ms=4.47,
        gradient_pct=0.0,
        dist_limit_cm=5905.0,
        next_limit_ms=6.71,
        lever_notch=3,
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=24025.9,
        limit_brake_enabled=True,
        station_brake_enabled=True,
        station_fsm="DEPARTING",
    )
    assert decision.reason == "release"
    assert decision.command is not None
    assert decision.command.kind == "RELEASE"


def test_departing_no_release_ipc_with_throttle_and_residual_air_session_182951() -> None:
    """DEPARTING+tracción: aire residual no dispara RELEASE si palanca ya en P (193606Z)."""
    snap = ProbeSnapshot(
        speed_ms=0.0,
        speed_limit_ms=10.0 / 2.237,
        gradient_pct=0.0,
        dist_limit_cm=5910.0,
        next_limit_ms=15.0 / 2.237,
        lever_notch=5,
        brake_cyl_bar=1.6,
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=24182.5,
        limit_brake_enabled=True,
        station_brake_enabled=True,
        station_fsm="DEPARTING",
    )
    assert decision.reason != "release"
    assert decision.command is None or decision.command.kind != "RELEASE"


def test_platform_bleed_no_reapply_while_episode_active_session_195804() -> None:
    """Tras B1 bleed: no repetir APPLY en neutro con episodio activo (195804Z)."""
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 0.0,
            "lever_notch": 4,
            "brake_cyl_bar": 5.16,
            "dist_limit_cm": 12174.3,
            "next_limit_ms": 6.7056,
            "speed_limit_ms": 4.4704,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=1523.1,
        limit_brake_enabled=True,
        station_brake_enabled=True,
        platform_bleed_episode=True,
    )
    assert decision.reason != "platform_bleed"
    assert decision.command is None or decision.command.kind != "APPLY"


def test_platform_bleed_release_after_apply_session_195804() -> None:
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 0.0,
            "lever_notch": 3,
            "brake_cyl_bar": 5.16,
            "dist_limit_cm": 12174.3,
            "next_limit_ms": 6.7056,
            "speed_limit_ms": 4.4704,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=1523.1,
        limit_brake_enabled=True,
        station_brake_enabled=True,
        platform_bleed_episode=True,
    )
    assert decision.reason == "platform_bleed_release"
    assert decision.command is not None
    assert decision.command.kind == "RELEASE"


def test_platform_bleed_apply_neutral_high_pressure_session_193606() -> None:
    """Five Ways: neutro + 5 bar — B1 para ventilar antes de arrancar."""
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 23528,
            "speed_ms": 0.0,
            "lever_notch": 4,
            "brake_cyl_bar": 5.16,
            "train_brake": 0.0,
            "dist_limit_cm": 12174.3,
            "next_limit_ms": 6.7056,
            "speed_limit_ms": 4.4704,
            "gradient_pct": 0.0,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=1523.1,
        limit_brake_enabled=True,
        station_brake_enabled=True,
    )
    assert decision.reason == "platform_bleed"
    assert decision.command is not None
    assert decision.command.kind == "APPLY"


def test_no_release_while_departing_with_throttle_at_neutral_session_214610() -> None:
    """Arranque: tracción + neutro — no RELEASE repetidos (214610Z)."""
    snap = ProbeSnapshot(
        speed_ms=0.0,
        speed_limit_ms=4.47,  # 10 mph vigente
        gradient_pct=0.0,
        dist_limit_cm=5910.0,
        next_limit_ms=6.71,  # 15 mph
        lever_notch=6,
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=24182.5,
        limit_brake_enabled=True,
        station_brake_enabled=True,
        station_fsm="DEPARTING",
    )
    assert decision.reason != "release"
    assert decision.command is None or decision.command.kind != "RELEASE"


def test_no_limit_release_final_approach_session_213633():
    """213633Z: RELEASE cartel @ 62 m abandonó freno estación."""
    state = LimitBrakeState()
    state.committed_handle = 3
    state.committed_phase = "B3"
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 7.55,  # ~16.9 mph
            "lever_notch": 2,
            "brake_cyl_bar": 2.5,
            "dist_limit_cm": 89500.0,
            "next_limit_ms": 20.1168,  # 45 mph
            "speed_limit_ms": 24.5872,  # zona 55
            "gradient_pct": 0.0,
        }
    )
    decision = evaluate_p1_tick(
        state,
        BrakeReleaseState(),
        snap,
        station_distance_m=62.0,
        limit_brake_enabled=True,
        station_brake_enabled=True,
    )
    assert decision.reason != "release"
    assert decision.command is None or decision.command.kind != "RELEASE"


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


def test_p1_tick_mid_route_service_parked_no_limit_release_session_191546() -> None:
    """Five Ways 2R99: neutro en andén (~1.5 km al next) — sin RELEASE cartel repetido."""
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 3436,
            "speed_ms": 0.0,
            "lever_notch": 4,
            "brake_cyl_bar": 2.5,
            "train_brake": 0.0,
            "dist_limit_cm": 12174.3,
            "next_limit_ms": 6.7056,
            "speed_limit_ms": 4.4704,
            "gradient_pct": 0.0,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=1523.1,
        limit_brake_enabled=True,
        station_brake_enabled=True,
    )
    assert decision.reason != "release"
    assert decision.command is None or decision.command.kind != "RELEASE"


def test_p1_tick_station_apply_after_signal_cluster_session_155851() -> None:
    """Longbridge: neutro ~13 mph @54 m tras señal — APPLY andén, no no_plan."""
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 5.82,  # ~13 mph
            "lever_notch": 4,
            "brake_cyl_bar": 1.03,
            "dist_limit_cm": 3810.0,  # lim ~38 m
            "next_limit_ms": 40.23,  # 90 mph
            "speed_limit_ms": 8.94,  # 20 mph
            "gradient_pct": 0.33,
            "signal_red": None,
            "signal_dist_cm": None,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=54.9,
        limit_brake_enabled=True,
        station_brake_enabled=True,
        signal_brake_enabled=True,
    )
    assert decision.target_kind == "STATION"
    assert decision.reason != "no_plan"
    assert decision.command is not None
    assert decision.command.kind == "APPLY"
