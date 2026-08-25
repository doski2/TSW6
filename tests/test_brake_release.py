#!/usr/bin/env python3
"""Tests RELEASE y anti-rebrake (brake_command.py)."""

from tsw6.braking.v2.command import (
    BrakeCommand,
    BrakeReleaseState,
    is_brake_applied,
    resolve_release_command,
)
from tsw6.braking.v2.plan import BrakePlan, BrakePlanStep
from tsw6.braking.v2.coordinator import BrakeCoordinatorV2


def _minimal_plan() -> BrakePlan:
    step = BrakePlanStep(
        notch="B2",
        handle_notch=2,
        phase="service",
        distance_m=500.0,
        apply_at_remaining_m=400.0,
        dist_start=50.0,
        meters_until_action_m=50.0,
        apply_now=True,
    )
    return BrakePlan(
        target_kind="SPEED_LIMIT",
        distance_to_target_m=500.0,
        target_speed_mph=50.0,
        reaction_margin_m=50.0,
        steps=[step],
        active_step=step,
    )


def test_is_brake_applied():
    assert is_brake_applied(3)
    assert not is_brake_applied(4)


def test_resolve_release_when_at_target():
    cmd = resolve_release_command(
        speed_mph=50.2,
        handle_notch=2,
        effective_limit=75.0,
        next_limit_mph=50.0,
        distance_next_m=200.0,
        gradient_pct=0.0,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"
    assert cmd.target_notch == 4


def test_no_release_when_slightly_above_limit():
    """Histéresis: no soltar a 51 mph con cartel 50 (antes soltaba hasta +2 mph)."""
    cmd = resolve_release_command(
        speed_mph=51.0,
        handle_notch=2,
        effective_limit=75.0,
        next_limit_mph=50.0,
        distance_next_m=200.0,
        gradient_pct=0.0,
    )
    assert cmd is None


def test_no_release_when_too_fast():
    cmd = resolve_release_command(
        speed_mph=58.0,
        handle_notch=2,
        effective_limit=75.0,
        next_limit_mph=50.0,
        distance_next_m=200.0,
        gradient_pct=0.0,
    )
    assert cmd is None


def test_no_release_when_already_neutral():
    cmd = resolve_release_command(
        speed_mph=50.0,
        handle_notch=4,
        effective_limit=75.0,
        next_limit_mph=50.0,
        distance_next_m=200.0,
        gradient_pct=0.0,
    )
    assert cmd is None


def test_coast_latch_inhibits_rebrake():
    state = BrakeReleaseState()
    state.latch(50.0)
    plan = _minimal_plan()
    assert state.should_inhibit_limit_rebrake(
        speed_mph=52.0,
        next_limit_mph=50.0,
        handle_notch=4,
        plan=plan,
        gradient_pct=0.0,
        distance_next_m=300.0,
        effective_limit=75.0,
    )


def test_no_release_without_next_limit():
    cmd = resolve_release_command(
        speed_mph=40.0,
        handle_notch=2,
        effective_limit=50.0,
        next_limit_mph=None,
        distance_next_m=None,
        gradient_pct=0.0,
    )
    assert cmd is None


def test_release_station_plan_when_stopped():
    step = BrakePlanStep(
        notch="B3",
        handle_notch=1,
        phase="3",
        distance_m=20.0,
        apply_at_remaining_m=30.0,
        dist_start=-5.0,
        meters_until_action_m=0.0,
        apply_now=True,
    )
    plan = BrakePlan(
        target_kind="STATION",
        distance_to_target_m=20.0,
        target_speed_mph=0.0,
        reaction_margin_m=10.0,
        steps=[step],
        active_step=step,
    )
    cmd = resolve_release_command(
        speed_mph=1.0,
        handle_notch=1,
        effective_limit=55.0,
        next_limit_mph=None,
        distance_next_m=None,
        gradient_pct=0.0,
        plan=plan,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"


def test_coast_latch_clears_on_limit_change():
    state = BrakeReleaseState()
    state.latch(50.0)
    state.update(52.0, 45.0)
    plan = _minimal_plan()
    assert not state.should_inhibit_limit_rebrake(
        speed_mph=52.0,
        next_limit_mph=45.0,
        handle_notch=4,
        plan=plan,
        gradient_pct=0.0,
        distance_next_m=300.0,
        effective_limit=75.0,
    )


def test_coordinator_releases_when_stopped_far_from_platform_marker():
    """Parada telemetría a 650 m pero spd≈0 — debe soltar (Four Oaks log)."""
    coord = BrakeCoordinatorV2()

    action, _ = coord.evaluate(
        speed_mph=0.5,
        next_limit_mph=55.0,
        distance_next_m=392.0,
        effective_limit=60.0,
        gradient_pct=-1.0,
        acceleration_ms2=None,
        throttle_notch=0,
        handle_notch=1,
        base_decel_ms2=0.80,
        station_distance_m=654.0,
        station_name="Four Oaks",
    )
    assert action == "RELEASE"
