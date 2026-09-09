from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.limit_station_cluster import (
    merged_approach_overspeed,
    next_sign_is_reduction_beyond_station,
    station_waits_for_approach_limit,
    will_be_below_limit_at_pass,
)
from tsw6v2.p1_policy import (
    pick_p1_brake_target,
    should_defer_station_brake,
    should_prefer_station_in_approach,
)
from tsw6v2.station_brake import evaluate_station_brake
from tsw6v2.station_plan import STATION_SCHEDULE_SLACK_ENABLED, plan_brake_for_station
from tsw6v2.target import BrakeTargetResult


def test_station_schedule_slack_disabled_by_default():
    assert STATION_SCHEDULE_SLACK_ENABLED is False
    with_eta = plan_brake_for_station(
        speed_mph=40.0,
        station_distance_m=800.0,
        station_eta="12:00",
        schedule_slack_enabled=False,
    )
    without = plan_brake_for_station(
        speed_mph=40.0,
        station_distance_m=800.0,
        schedule_slack_enabled=False,
    )
    assert with_eta is not None and without is not None
    assert with_eta.active_step is not None and without.active_step is not None
    assert with_eta.active_step.handle_notch == without.active_step.handle_notch


def test_should_defer_station_far():
    assert should_defer_station_brake(speed_mph=60.0, station_dist_m=5000.0)


def test_station_brake_near_platform():
    target = evaluate_station_brake(
        speed_mph=25.0,
        station_distance_m=120.0,
        gradient_pct=0.0,
    )
    assert target is not None
    assert target.target_kind == "STATION"
    assert target.handle_notch >= 1


def test_pick_station_when_in_service_horizon():
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=60.0,
        target_speed_mph=55.0,
        handle_notch=3,
        phase="B1",
        dist_start=150.0,
        apply_now=False,
        detail="limit",
    )
    station = BrakeTargetResult(
        target_kind="STATION",
        distance_m=90.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=10.0,
        apply_now=True,
        detail="station",
    )
    picked = pick_p1_brake_target(
        speed_mph=25.0,
        limit_target=limit,
        station_target=station,
        limit_mph=55.0,
        limit_dist_m=60.0,
        station_dist_m=90.0,
        effective_limit=60.0,
    )
    assert picked is not None
    assert picked.target_kind == "STATION"


def test_no_wait_when_next_limit_is_past_station_cluster():
    """Tras pasar 55 en cluster: next 45 @ 964 m no bloquea STATION @ 281 m."""
    assert not next_sign_is_reduction_beyond_station(
        limit_mph=45.0,
        limit_dist_m=964.0,
        station_dist_m=281.0,
        current_limit_mph=55.0,
    )
    assert not station_waits_for_approach_limit(
        speed_mph=52.2,
        limit_mph=45.0,
        limit_dist_m=964.0,
        station_dist_m=281.0,
        current_limit_mph=55.0,
    )


def test_wait_when_reduction_clustered_before_station():
    """Four Oaks invertido: cartel 55 más lejos que andén, aún en cluster."""
    assert next_sign_is_reduction_beyond_station(
        limit_mph=55.0,
        limit_dist_m=320.0,
        station_dist_m=180.0,
        current_limit_mph=60.0,
    )


def test_pick_limit_when_merged_approach_overspeed():
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=120.0,
        target_speed_mph=55.0,
        handle_notch=3,
        phase="B1",
        dist_start=80.0,
        apply_now=True,
        detail="limit",
    )
    station = BrakeTargetResult(
        target_kind="STATION",
        distance_m=200.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=30.0,
        apply_now=True,
        detail="station",
    )
    assert merged_approach_overspeed(
        speed_mph=58.0,
        limit_mph=55.0,
        limit_dist_m=120.0,
        station_dist_m=200.0,
    )
    picked = pick_p1_brake_target(
        speed_mph=58.0,
        limit_target=limit,
        station_target=station,
        limit_mph=55.0,
        limit_dist_m=120.0,
        station_dist_m=200.0,
        effective_limit=60.0,
    )
    assert picked is not None
    assert picked.target_kind == "SPEED_LIMIT"


def test_should_prefer_station_in_approach_watch_only():
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=158.0,
        target_speed_mph=55.0,
        handle_notch=0,
        phase="WATCH",
        dist_start=0.0,
        apply_now=False,
        detail="limit",
    )
    assert should_prefer_station_in_approach(
        speed_mph=37.0,
        station_dist_m=444.0,
        limit_target=limit,
    )
    limit_apply = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=158.0,
        target_speed_mph=55.0,
        handle_notch=3,
        phase="B1",
        dist_start=80.0,
        apply_now=True,
        detail="limit",
    )
    # Sin limit_mph/dist: rama WATCH-only (API directa).
    assert not should_prefer_station_in_approach(
        speed_mph=37.0,
        station_dist_m=444.0,
        limit_target=limit_apply,
    )
    # Con cartel delante y proyección legal: APPLY ya no bloquea STATION.
    assert should_prefer_station_in_approach(
        speed_mph=37.0,
        station_dist_m=444.0,
        limit_target=limit_apply,
        limit_mph=55.0,
        limit_dist_m=158.0,
    )


def test_pick_station_after_passed_cluster_limit():
    """Sesión 20260909T230944Z: tras pasar 55, no volver a SPEED_LIMIT WATCH."""
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=964.0,
        target_speed_mph=45.0,
        handle_notch=0,
        phase="WATCH",
        dist_start=0.0,
        apply_now=False,
        detail="limit",
    )
    station = BrakeTargetResult(
        target_kind="STATION",
        distance_m=281.0,
        target_speed_mph=0.0,
        handle_notch=2,
        phase="B2",
        dist_start=10.0,
        apply_now=True,
        detail="station",
    )
    picked = pick_p1_brake_target(
        speed_mph=52.2,
        limit_target=limit,
        station_target=station,
        limit_mph=45.0,
        limit_dist_m=964.0,
        station_dist_m=281.0,
        effective_limit=55.0,
    )
    assert picked is not None
    assert picked.target_kind == "STATION"


def test_pick_station_in_approach_when_limit_watch_only():
    """Sesión 20260909T224556Z: cartel WATCH @ 158 m no debe ganar al andén @ 444 m."""
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=158.0,
        target_speed_mph=55.0,
        handle_notch=0,
        phase="WATCH",
        dist_start=0.0,
        apply_now=False,
        detail="limit",
    )
    station = BrakeTargetResult(
        target_kind="STATION",
        distance_m=444.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=10.0,
        apply_now=True,
        detail="station",
    )
    picked = pick_p1_brake_target(
        speed_mph=37.0,
        limit_target=limit,
        station_target=station,
        limit_mph=55.0,
        limit_dist_m=158.0,
        station_dist_m=444.0,
        effective_limit=60.0,
    )
    assert picked is not None
    assert picked.target_kind == "STATION"


def test_pick_none_when_deferred_and_limit_watch_far():
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=2000.0,
        target_speed_mph=55.0,
        handle_notch=0,
        phase="WATCH",
        dist_start=0.0,
        apply_now=False,
        detail="limit",
    )
    station = BrakeTargetResult(
        target_kind="STATION",
        distance_m=5000.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=50.0,
        apply_now=True,
        detail="station",
    )
    picked = pick_p1_brake_target(
        speed_mph=50.0,
        limit_target=limit,
        station_target=station,
        limit_mph=55.0,
        limit_dist_m=2000.0,
        station_dist_m=5000.0,
        effective_limit=60.0,
    )
    assert picked is None


def test_will_be_below_limit_at_pass_coasting():
    assert will_be_below_limit_at_pass(
        speed_mph=52.0,
        limit_mph=55.0,
        limit_dist_m=120.0,
        gradient_pct=-1.0,
    )
    assert not will_be_below_limit_at_pass(
        speed_mph=58.0,
        limit_mph=55.0,
        limit_dist_m=120.0,
        gradient_pct=-1.0,
    )


def test_pick_station_when_below_limit_at_pass_despite_limit_apply():
    """Sesión 231617Z: bajo 55 mph → STATION aunque cartel pida APPLY."""
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=98.0,
        target_speed_mph=55.0,
        handle_notch=3,
        phase="B1",
        dist_start=40.0,
        apply_now=True,
        detail="limit",
    )
    station = BrakeTargetResult(
        target_kind="STATION",
        distance_m=384.0,
        target_speed_mph=0.0,
        handle_notch=2,
        phase="B2",
        dist_start=10.0,
        apply_now=True,
        detail="station",
    )
    picked = pick_p1_brake_target(
        speed_mph=52.0,
        limit_target=limit,
        station_target=station,
        limit_mph=55.0,
        limit_dist_m=98.0,
        station_dist_m=384.0,
        effective_limit=60.0,
        gradient_pct=-1.0,
    )
    assert picked is not None
    assert picked.target_kind == "STATION"


def test_merged_approach_not_overspeed_when_below_limit_at_pass():
    assert not merged_approach_overspeed(
        speed_mph=52.0,
        limit_mph=55.0,
        limit_dist_m=120.0,
        station_dist_m=200.0,
        gradient_pct=-1.0,
    )


def test_pick_limit_when_station_waits_for_reduction():
    limit = BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=500.0,
        target_speed_mph=55.0,
        handle_notch=3,
        phase="B1",
        dist_start=100.0,
        apply_now=True,
        detail="limit",
    )
    station = BrakeTargetResult(
        target_kind="STATION",
        distance_m=800.0,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=50.0,
        apply_now=True,
        detail="station",
    )
    picked = pick_p1_brake_target(
        speed_mph=62.0,
        limit_target=limit,
        station_target=station,
        limit_mph=55.0,
        limit_dist_m=500.0,
        station_dist_m=800.0,
        effective_limit=60.0,
    )
    assert picked is not None
    assert picked.target_kind == "SPEED_LIMIT"
