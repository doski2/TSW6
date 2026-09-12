from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.physics import coast_trim_covers_overspeed


def test_coast_trim_small_overspeed_downhill() -> None:
    assert coast_trim_covers_overspeed(
        speed_mph=55.5,
        target_mph=54.0,
        distance_m=500.0,
        gradient_pct=-1.0,
    )


def test_coast_trim_defers_uphill_60_to_55() -> None:
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert downhill_defer_brake_commit(
        speed_mph=55.5,
        ops_target_mph=54.0,
        distance_m=600.0,
        gradient_pct=1.0,
        dist_start=80.0,
        current_posted_mph=60.0,
        next_posted_mph=55.0,
    )


def test_coast_trim_defers_uphill_60_to_50_session_201211() -> None:
    """57 mph @ +1% y ~250 m: coast en cuesta basta; no B1 (sesión 201211Z)."""
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert downhill_defer_brake_commit(
        speed_mph=57.0,
        ops_target_mph=49.0,
        distance_m=256.0,
        gradient_pct=1.0,
        dist_start=50.0,
        current_posted_mph=60.0,
        next_posted_mph=50.0,
    )


def test_coast_trim_uphill_defer_past_kinematic_ds_session_203100() -> None:
    """ds<0 pero 95 m al cartel: coast en cuesta sigue diferido (203100Z)."""
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert downhill_defer_brake_commit(
        speed_mph=56.67,
        ops_target_mph=54.0,
        distance_m=94.8,
        gradient_pct=1.0,
        dist_start=0.2,
        current_posted_mph=60.0,
        next_posted_mph=55.0,
    )
    assert downhill_defer_brake_commit(
        speed_mph=56.61,
        ops_target_mph=54.0,
        distance_m=93.6,
        gradient_pct=1.0,
        dist_start=-0.7,
        current_posted_mph=60.0,
        next_posted_mph=55.0,
    )


def test_coast_trim_uphill_stops_defer_when_too_close() -> None:
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert not downhill_defer_brake_commit(
        speed_mph=59.0,
        ops_target_mph=49.0,
        distance_m=45.0,
        gradient_pct=1.0,
        dist_start=10.0,
        current_posted_mph=60.0,
        next_posted_mph=50.0,
    )


def test_coast_trim_not_large_overspeed() -> None:
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert not downhill_defer_brake_commit(
        speed_mph=60.0,
        ops_target_mph=54.0,
        distance_m=500.0,
        gradient_pct=-1.0,
        dist_start=100.0,
        current_posted_mph=55.0,
        next_posted_mph=55.0,
    )


def test_coast_trim_defers_while_legal_in_current_zone() -> None:
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert downhill_defer_brake_commit(
        speed_mph=55.0,
        ops_target_mph=54.0,
        distance_m=800.0,
        gradient_pct=-1.0,
        dist_start=80.0,
        current_posted_mph=60.0,
        next_posted_mph=55.0,
    )


def test_descending_zone_no_defer_when_fast_approach_60_to_55() -> None:
    """Sesión 20260908T200808Z: 59–60 mph @ ~740 m no debe bloquear B1 al 55."""
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert not downhill_defer_brake_commit(
        speed_mph=59.5,
        ops_target_mph=54.0,
        distance_m=740.0,
        gradient_pct=-1.0,
        dist_start=565.0,
        current_posted_mph=60.0,
        next_posted_mph=55.0,
    )


def test_hold_dh_over_watch_outside_horizon_session_210357() -> None:
    """60.53 mph @ 717 m: HOLD_DH @60.2, no WATCH con tracción (sesión 210357Z)."""
    from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake

    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=60.53,
        limit_mph=55.0,
        distance_m=717.4,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert r.downhill_hold
    assert r.apply_now
    assert r.target_speed_mph == 60.2
    assert r.handle_notch == 3


def test_next_brake_overrides_hold_dh_session_profile() -> None:
    """Dentro del horizonte: BRAKE_LIMIT al 55 gana sobre HOLD_DH zona 60."""
    from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake

    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=60.0,
        limit_mph=55.0,
        distance_m=280.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert not r.downhill_hold
    assert r.target_speed_mph == 54.0
    assert r.apply_now
    assert "55" in r.detail


def test_descending_zone_no_defer_inside_brake_horizon() -> None:
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert not downhill_defer_brake_commit(
        speed_mph=58.0,
        ops_target_mph=54.0,
        distance_m=80.0,
        gradient_pct=-1.0,
        dist_start=10.0,
        current_posted_mph=60.0,
        next_posted_mph=55.0,
    )


def test_uphill_early_coast_when_brake_deferred_session_201456() -> None:
    """54 mph @ +0.93 %%, B1 diferido lejos: COAST_PWR, no quedarse en P6."""
    from tsw6v2.command import command_from_target

    cmd = command_from_target(
        target_kind="SPEED_LIMIT",
        distance_m=3980.0,
        target_speed_mph=34.0,
        handle_notch=3,
        phase="B1",
        dist_start=3535.0,
        apply_now=False,
        throttle_notch=6,
        current_notch=6,
        speed_mph=54.5,
        gradient_pct=0.93,
        coast_trim_deferred=True,
    )
    assert cmd is not None
    assert cmd.kind == "COAST_THROTTLE"


def test_no_early_coast_without_coast_trim_deferred() -> None:
    from tsw6v2.command import command_from_target

    cmd = command_from_target(
        target_kind="SPEED_LIMIT",
        distance_m=3980.0,
        target_speed_mph=34.0,
        handle_notch=3,
        phase="B1",
        dist_start=3535.0,
        apply_now=False,
        throttle_notch=6,
        current_notch=6,
        speed_mph=54.5,
        gradient_pct=0.93,
        coast_trim_deferred=False,
    )
    assert cmd is None


def test_no_hold_dh_uphill_ascending_exit_session_201456() -> None:
    """45→60 @ +1 %%: no B1 HOLD_DH al salir de zona lenta."""
    from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake

    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=45.58,
        limit_mph=60.0,
        distance_m=724.4,
        gradient_pct=1.05,
        posted_limit_mph=45.0,
    )
    assert r is None or not r.downhill_hold


def test_coast_trim_not_when_over_current_ops_band() -> None:
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert not downhill_defer_brake_commit(
        speed_mph=62.0,
        ops_target_mph=54.0,
        distance_m=500.0,
        gradient_pct=-1.0,
        dist_start=80.0,
        current_posted_mph=60.0,
        next_posted_mph=55.0,
    )
