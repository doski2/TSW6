#!/usr/bin/env python3
"""Tests brake_release.py — RELEASE Dastsc."""

from brake_command import BrakeCommand
from brake_planner import BrakePlan, BrakePlanStep
from brake_release import (
    BrakeReleaseState,
    resolve_release_command,
    is_brake_applied,
)


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
        speed_mph=51.0,
        handle_notch=2,
        effective_limit=75.0,
        next_limit_mph=50.0,
        distance_next_m=200.0,
        gradient_pct=0.0,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"
    assert cmd.target_notch == 4


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
