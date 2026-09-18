from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeReleaseState
from tsw6v2.decision import evaluate_p1_tick
from tsw6v2.limits import LimitBrakeState
from tsw6v2.p1_policy import (
    limit_release_allowed,
    pick_p1_brake_target,
    should_prefer_signal_over_limit,
    should_prefer_signal_over_station,
)
from tsw6v2.station_brake import evaluate_station_brake
from tsw6v2.signal_plan import (
    exit_signal_close_behind_platform,
    signal_behind_station,
    signal_deferred_to_station_at_platform,
    signal_in_play,
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
        signal_distance_m=80.0,
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


def test_signal_behind_station_when_station_closer_session_150617():
    """Rojo tras andén: stn 120 m, sig 280 m — no planificar parada al semáforo."""
    assert signal_behind_station(signal_dist_m=280.0, station_dist_m=120.0)
    assert not signal_in_play(signal_dist_m=280.0, station_dist_m=120.0)
    assert exit_signal_close_behind_platform(signal_dist_m=25.6, station_dist_m=21.7)
    assert signal_in_play(signal_dist_m=25.6, station_dist_m=21.7)


def test_signal_deferred_to_station_at_platform_session_164240():
    assert signal_deferred_to_station_at_platform(
        signal_dist_m=280.0,
        station_dist_m=120.0,
    )
    assert signal_deferred_to_station_at_platform(
        signal_dist_m=133.0,
        station_dist_m=137.0,
    )
    assert not signal_deferred_to_station_at_platform(
        signal_dist_m=620.0,
        station_dist_m=1141.0,
    )
    assert not signal_deferred_to_station_at_platform(
        signal_dist_m=25.6,
        station_dist_m=21.7,
    )


def test_p1_tick_station_not_signal_when_red_after_platform_session_150617():
    """Aproximación andén con rojo de salida ~160 m más allá: STATION + límites, no SIGNAL."""
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 8.94,  # ~20 mph
            "lever_notch": 6,
            "signal_red": True,
            "signal_dist_cm": 28000.0,
            "speed_limit_ms": 6.7056,  # 15 mph zona
            "dist_limit_cm": 80000.0,
            "next_limit_ms": 22.352,  # 50 mph
            "gradient_pct": -1.74,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=120.0,
    )
    assert decision.target_kind != "SIGNAL"
    assert decision.target_kind in ("STATION", "SPEED_LIMIT")


def test_signal_in_play():
    assert not signal_in_play(signal_dist_m=500.0, station_dist_m=200.0)
    assert signal_in_play(signal_dist_m=29.0, station_dist_m=31.0)
    assert not signal_in_play(signal_dist_m=None, station_dist_m=200.0)


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


def test_should_prefer_signal_over_limit_when_close_beats_limit_apply_session_155148():
    """Rojo @100 m gana a cartel 15 con APPLY (GAP lim sin mandó, 155148Z)."""
    signal = BrakeTargetResult(
        target_kind="SIGNAL",
        distance_m=100.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=50.0,
        apply_now=False,
        detail="",
    )
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=320.0,
        target_speed_mph=14.0,
        handle_notch=3,
        phase="B1",
        dist_start=157.0,
        apply_now=True,
        detail="",
    )
    assert should_prefer_signal_over_limit(
        signal,
        limit,
        signal_dist_m=100.0,
    )


def test_signal_apply_horizon_extended_above_30_mph_session_155148():
    """@32 mph y 100 m: APPLY (horizonte 150 m); @20 mph y 217 m: WATCH."""
    fast = evaluate_signal_brake(
        speed_mph=32.0,
        signal_distance_m=100.0,
        gradient_pct=-1.0,
        throttle_notch=0,
    )
    assert fast is not None
    assert fast.apply_now is True
    far = evaluate_signal_brake(
        speed_mph=20.0,
        signal_distance_m=217.0,
        gradient_pct=-1.0,
        throttle_notch=0,
    )
    assert far is None or far.apply_now is False


def test_should_prefer_signal_over_limit_when_apply():
    signal = BrakeTargetResult(
        target_kind="SIGNAL",
        distance_m=500.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=200.0,
        apply_now=True,
        detail="",
    )
    assert should_prefer_signal_over_limit(signal, _limit_watch())


def test_signal_watch_far_defers_to_limit_hold_dh_session_102222():
    signal = BrakeTargetResult(
        target_kind="SIGNAL",
        distance_m=283.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=180.0,
        apply_now=False,
        detail="",
    )
    hold = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=280.0,
        target_speed_mph=15.2,
        handle_notch=3,
        phase="B1",
        dist_start=0.0,
        apply_now=True,
        downhill_hold=True,
        detail="",
    )
    assert not should_prefer_signal_over_limit(
        signal,
        hold,
        signal_dist_m=283.0,
    )


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


def test_signal_watch_releases_inherited_b3_far_red_session_083405():
    """Rojo @ 1 km con B3 heredado del cartel 45: soltar a neutro (sesión 083405Z)."""
    target = evaluate_signal_brake(
        speed_mph=53.0,
        signal_distance_m=1040.0,
        gradient_pct=-0.2,
        throttle_notch=0,
    )
    assert target is not None
    assert target.apply_now is False
    cmd = target.to_brake_command(current_notch=1, speed_mph=53.0)
    assert cmd is not None
    assert cmd.kind == "RELEASE"
    assert cmd.target_notch == 4


def test_signal_plan_persists_at_crawl_speed_far_from_post():
    target = evaluate_signal_brake(
        speed_mph=1.0,
        signal_distance_m=750.0,
        gradient_pct=-0.2,
        throttle_notch=0,
    )
    assert target is not None
    assert target.target_kind == "SIGNAL"


def test_signal_no_apply_far_from_red_session_152037():
    """@217 m: WATCH o sin APPLY (horizonte ~100 yd); no parada total lejos."""
    target = evaluate_signal_brake(
        speed_mph=20.0,
        signal_distance_m=217.0,
        gradient_pct=-1.74,
        throttle_notch=0,
    )
    assert target is None or target.apply_now is False


def test_signal_apply_within_horizon_session_152037():
    """@80 m: APPLY dentro de ~100 yd."""
    target = evaluate_signal_brake(
        speed_mph=20.0,
        signal_distance_m=80.0,
        gradient_pct=-1.74,
        throttle_notch=0,
    )
    assert target is not None
    assert target.apply_now is True


def test_signal_immediate_stop_crawl_near_post_session_102222():
    """@70 m y ~1 mph: APPLY ahora (dentro de horizonte ~100 yd)."""
    plan = plan_brake_for_signal(
        speed_mph=1.0,
        signal_distance_m=70.0,
        gradient_pct=-1.74,
    )
    assert plan is not None
    assert plan.active_step is not None
    assert plan.active_step.apply_now is True


def test_limit_release_blocked_crawl_far_from_red_signal_session_102222():
    signal = BrakeTargetResult(
        target_kind="SIGNAL",
        distance_m=70.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=0.0,
        apply_now=True,
        detail="",
    )
    assert not limit_release_allowed(
        None,
        None,
        signal_target=signal,
        signal_dist_m=70.0,
        speed_mph=0.7,
    )
    # Lejos del horizonte: creep permitido para acercarse (152037Z @217 m).
    assert limit_release_allowed(
        None,
        None,
        signal_target=None,
        signal_dist_m=217.0,
        speed_mph=0.7,
    )


def test_signal_cleared_release_blocked_during_downhill_hold_session_211133():
    """Verde tras rojo: no RELEASE si HOLD_DH cartel activo (211133Z @31 mph)."""
    state = LimitBrakeState()
    snap = ProbeSnapshot(
        speed_ms=13.94,  # ~31.2 mph
        speed_limit_ms=13.4112,  # 30 mph
        gradient_pct=-0.67,
        dist_limit_cm=77640.0,
        next_limit_ms=22.352,  # 50 mph
        lever_notch=3,
        signal_red=False,
    )
    decision = evaluate_p1_tick(
        state,
        BrakeReleaseState(),
        snap,
        station_distance_m=23700.0,
        limit_brake_enabled=True,
        station_brake_enabled=True,
        signal_brake_enabled=True,
    )
    assert decision.reason == "downhill_hold"
    assert decision.command is not None
    assert decision.command.kind == "APPLY"


def test_limit_release_allowed_exit_signal_far_session_150617():
    """Rojo salida @280 m con andén @120 m: no bloquear RELEASE por creep de señal."""
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=800.0,
        target_speed_mph=15.2,
        handle_notch=3,
        phase="B1",
        dist_start=0.0,
        apply_now=True,
        downhill_hold=True,
        detail="",
    )
    assert limit_release_allowed(
        120.0,
        limit,
        signal_target=None,
        signal_dist_m=280.0,
        speed_mph=5.0,
    )


def test_limit_release_blocked_signal_red_crawl_inside_horizon_session_143544():
    """Rojo @70 m crawl: no RELEASE aunque signal_target sea None (143544Z)."""
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=283.0,
        target_speed_mph=15.2,
        handle_notch=3,
        phase="B1",
        dist_start=0.0,
        apply_now=True,
        downhill_hold=True,
        detail="",
    )
    assert not limit_release_allowed(
        None,
        limit,
        signal_target=None,
        signal_dist_m=70.0,
        speed_mph=0.42,
    )


def test_signal_plan_at_ultra_crawl_inside_horizon_session_143544():
    """@0.42 mph y 70 m: plan señal activo (dentro de ~100 yd)."""
    target = evaluate_signal_brake(
        speed_mph=0.42,
        signal_distance_m=70.0,
        gradient_pct=-1.74,
        throttle_notch=0,
    )
    assert target is not None
    assert target.target_kind == "SIGNAL"
    assert target.apply_now is True


def test_p1_tick_release_after_signal_cleared_session_152037():
    """Tras pasar semáforo (rojo off): soltar B3 heredado."""
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 2.0,
            "lever_notch": 1,
            "speed_limit_ms": 13.4,
            "signal_red": False,
            "signal_dist_cm": 0.0,
            "gradient_pct": -1.74,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=None,
    )
    assert decision.reason == "release"
    assert decision.command is not None
    assert decision.command.kind == "RELEASE"


def test_p1_tick_no_release_when_signal_red_unknown():
    """``signal_red=None`` no cuenta como verde (no RELEASE heredado)."""
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 2.0,
            "lever_notch": 1,
            "speed_limit_ms": 13.4,
            "signal_red": None,
            "gradient_pct": 0.0,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=None,
        limit_brake_enabled=False,
        station_brake_enabled=False,
    )
    assert decision.reason != "release"


def test_p1_tick_no_signal_cleared_release_in_platform_zone_session_213920():
    """213920Z: con plan STATION en zona andén no soltar por señal pasada/verde."""
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 27924,
            "speed_ms": 15.93 / 2.237,
            "lever_notch": 2,
            "brake_cyl_bar": 1.82,
            "speed_limit_ms": 20.0 / 2.237,
            "dist_limit_cm": 302.9 * 100.0,
            "next_limit_ms": 60.0 / 2.237,
            "signal_red": False,
            "gradient_pct": 0.0,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=54.8,
    )
    assert decision.target_kind == "STATION"
    assert decision.reason != "release"


def test_p1_tick_zone_hold_when_next_limit_glitch_session_143544():
    """Tick con lim=null pero eff=15: HOLD_DH, no flip a señal WATCH."""
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 4173,
            "speed_ms": 9.38,  # ~21 mph
            "lever_notch": 6,
            "speed_limit_ms": 6.7056,  # 15 mph
            "signal_red": True,
            "signal_dist_cm": 28300.0,
            "gradient_pct": -1.74,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=None,
    )
    assert decision.target_kind == "SPEED_LIMIT"
    assert decision.reason in ("plan", "downhill_hold", "air_fill", "coast_throttle")


def test_limit_release_blocked_when_station_apply_now_despite_speed_limit_pick():
    """213633Z: pick=SPEED_LIMIT no debe abrir RELEASE con plan STATION activo."""
    station = BrakeTargetResult(
        target_kind="STATION",
        distance_m=280.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B2",
        dist_start=-20.0,
        apply_now=True,
        detail="",
    )
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=900.0,
        target_speed_mph=44.0,
        handle_notch=3,
        phase="B2",
        dist_start=0.0,
        apply_now=True,
        detail="",
    )
    assert not limit_release_allowed(
        280.0,
        limit,
        station_target=station,
        speed_mph=34.0,
    )


def test_limit_release_blocked_station_watch_final_approach():
    """213633Z: WATCH en aproximación final — mantener freno, no soltar al cartel."""
    station = BrakeTargetResult(
        target_kind="STATION",
        distance_m=62.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B3",
        dist_start=-80.0,
        apply_now=False,
        detail="",
    )
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=900.0,
        target_speed_mph=44.0,
        handle_notch=3,
        phase="B2",
        dist_start=0.0,
        apply_now=False,
        detail="",
    )
    assert not limit_release_allowed(
        62.0,
        limit,
        station_target=station,
        speed_mph=17.0,
    )


def test_limit_release_allowed_when_signal_only_watch():
    signal = BrakeTargetResult(
        target_kind="SIGNAL",
        distance_m=1040.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=400.0,
        apply_now=False,
        detail="",
    )
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=500.0,
        target_speed_mph=44.0,
        handle_notch=3,
        phase="B1",
        dist_start=0.0,
        apply_now=True,
        detail="",
    )
    assert limit_release_allowed(
        None,
        limit,
        signal_target=signal,
        signal_dist_m=1040.0,
        speed_mph=53.0,
    )


def test_p1_tick_signal_watch_releases_b3_session_083405():
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 6439,
            "speed_ms": 23.7,
            "lever_notch": 1,
            "signal_red": True,
            "signal_dist_cm": 104070.0,
            "dist_limit_cm": 51090.0,
            "next_limit_ms": 20.12,
            "gradient_pct": -0.21,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=None,
    )
    assert decision.command is not None
    assert decision.command.kind == "RELEASE"
    assert decision.reason == "release"


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


def test_station_beats_exit_signal_cluster_session_164240() -> None:
    """Rojo de salida pegado al marker: STATION gana a SIGNAL (164240Z)."""
    signal = BrakeTargetResult(
        target_kind="SIGNAL",
        distance_m=133.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=50.0,
        apply_now=False,
        detail="signal",
    )
    station = BrakeTargetResult(
        target_kind="STATION",
        distance_m=137.0,
        target_speed_mph=0.0,
        handle_notch=2,
        phase="B2",
        dist_start=20.0,
        apply_now=True,
        detail="station",
    )
    assert not should_prefer_signal_over_station(signal, station)
    picked = pick_p1_brake_target(
        speed_mph=17.0,
        limit_target=None,
        station_target=station,
        signal_target=signal,
        signal_dist_m=133.0,
        limit_mph=50.0,
        limit_dist_m=126.0,
        station_dist_m=137.0,
        effective_limit=15.0,
        gradient_pct=-1.0,
    )
    assert picked is not None
    assert picked.target_kind == "STATION"


def test_signal_beats_station_exit_red_close_behind_marker_session_213920() -> None:
    """Rojo de salida ~4 m tras marker dentro de 91 m: SIGNAL gana (213920Z tick 32081)."""
    signal = BrakeTargetResult(
        target_kind="SIGNAL",
        distance_m=25.3,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=10.0,
        apply_now=True,
        detail="signal",
    )
    station = BrakeTargetResult(
        target_kind="STATION",
        distance_m=21.5,
        target_speed_mph=0.0,
        handle_notch=2,
        phase="B2",
        dist_start=8.0,
        apply_now=True,
        detail="station",
    )
    assert should_prefer_signal_over_station(signal, station, signal_dist_m=25.3)
    picked = pick_p1_brake_target(
        speed_mph=9.91,
        limit_target=None,
        station_target=station,
        signal_target=signal,
        signal_dist_m=25.3,
        limit_mph=60.0,
        limit_dist_m=700.0,
        station_dist_m=21.5,
        effective_limit=60.0,
        gradient_pct=-0.7,
    )
    assert picked is not None
    assert picked.target_kind == "SIGNAL"


def test_p1_tick_station_not_signal_exit_cluster_session_164240() -> None:
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 7.59,  # ~17 mph
            "lever_notch": 3,
            "signal_red": True,
            "signal_dist_cm": 13300.0,
            "speed_limit_ms": 6.7056,  # 15 mph zona
            "dist_limit_cm": 12600.0,
            "next_limit_ms": 22.352,  # 50 mph
            "gradient_pct": -1.0,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=137.0,
    )
    assert decision.target_kind == "STATION"
