#!/usr/bin/env python3
"""Tests brake_command.py — paridad ejecución Dastsc."""

from tsw6.braking.v2.command import (
    BrakeCommand,
    governor_action_for_command,
    plan_to_brake_command,
)
from tsw6.braking.v2.plan import BrakePlan, BrakePlanStep
from tsw6.braking.v2.planner import plan_brake


def _plan_with_step(*, apply_now: bool = True, dist_start: float = 10.0):
    plan = plan_brake(
        speed_mph=55.0,
        distance_to_target_m=800.0,
        target_speed_mph=50.0,
        gradient_pct=0.0,
        base_decel=0.8,
    )
    assert plan is not None
    step = plan.active_step
    assert step is not None
    plan.active_step = BrakePlanStep(
        notch=step.notch,
        handle_notch=step.handle_notch,
        phase=step.phase,
        distance_m=step.distance_m,
        apply_at_remaining_m=step.apply_at_remaining_m,
        dist_start=dist_start,
        meters_until_action_m=step.meters_until_action_m,
        apply_now=apply_now,
        using_learned=step.using_learned,
    )
    return plan


def test_governor_action_for_command_apply_is_hold():
    cmd = BrakeCommand(kind="APPLY", target_notch=2, phase="B2")
    assert governor_action_for_command(cmd) == "HOLD"


def test_governor_action_for_command_release():
    cmd = BrakeCommand(kind="RELEASE", target_notch=4)
    assert governor_action_for_command(cmd) == "RELEASE"


def test_plan_to_brake_command_apply_b1():
    plan = _plan_with_step()
    cmd, _ = plan_to_brake_command(
        plan,
        speed_mph=55.0,
        throttle_notch=0,
        effective_limit=75.0,
        current_notch=4,
    )
    assert cmd is not None
    assert cmd.kind == "APPLY"
    assert cmd.phase in ("B1", "B2", "B3")
    step = plan.active_step
    assert step is not None
    assert cmd.target_notch == step.handle_notch


def test_plan_to_brake_command_coast_when_throttle():
    plan = _plan_with_step()
    cmd, _ = plan_to_brake_command(
        plan,
        speed_mph=55.0,
        throttle_notch=2,
        effective_limit=75.0,
        current_notch=6,
    )
    assert cmd is not None
    assert cmd.kind == "COAST_THROTTLE"
    assert cmd.target_notch == 4


def test_brake_command_display():
    assert BrakeCommand("APPLY", 3, "B1").display_action() == "B1"


def test_clamp_brake_handle_service_only_far():
    from tsw6.braking.v2.command import clamp_brake_handle
    from tsw6.governor.governor_constants import SERVICE_MIN_HANDLE

    assert clamp_brake_handle(0, 200.0) == SERVICE_MIN_HANDLE
    assert clamp_brake_handle(0, 10.0) == 0
    assert clamp_brake_handle(2, 500.0) == 2


def test_plan_releases_when_at_limit_target():
    plan = _plan_with_step(dist_start=-80.0)
    cmd, _ = plan_to_brake_command(
        plan,
        speed_mph=51.0,
        throttle_notch=0,
        effective_limit=75.0,
        current_notch=1,
    )
    assert cmd is not None
    assert cmd.kind != "APPLY" or cmd.target_notch != 1


def test_station_plan_releases_when_stopped():
    plan = plan_brake(
        speed_mph=2.0,
        distance_to_target_m=30.0,
        target_speed_mph=0.0,
        target_kind="STATION",
    )
    assert plan is not None
    step = plan.active_step
    assert step is not None
    step.apply_now = True
    cmd, _ = plan_to_brake_command(
        plan,
        speed_mph=1.0,
        throttle_notch=0,
        effective_limit=55.0,
        current_notch=1,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"
    assert cmd.target_notch == 4
