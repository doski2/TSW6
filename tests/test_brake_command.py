#!/usr/bin/env python3
"""Tests brake_command.py — APPLY / RELEASE / COAST vía plan sintético P1."""

from tsw6.braking.v2.command import (
    BrakeCommand,
    governor_action_for_command,
    plan_to_brake_command,
)
from tsw6.braking.v2.plan import BrakePlan, BrakePlanStep, TargetKind


def _plan(
    *,
    target_kind: TargetKind = "SPEED_LIMIT",
    target_speed_mph: float = 50.0,
    distance_m: float = 800.0,
    apply_now: bool = True,
    dist_start: float = 10.0,
    notch: str = "B1",
    handle_notch: int = 3,
) -> BrakePlan:
    step = BrakePlanStep(
        notch=notch,
        handle_notch=handle_notch,
        phase="1",
        distance_m=200.0,
        apply_at_remaining_m=distance_m - dist_start,
        dist_start=dist_start,
        meters_until_action_m=max(0.0, dist_start),
        apply_now=apply_now,
    )
    return BrakePlan(
        target_kind=target_kind,
        distance_to_target_m=distance_m,
        target_speed_mph=target_speed_mph,
        reaction_margin_m=40.0,
        steps=[step],
        active_step=step,
    )


def test_governor_action_for_command_apply_is_hold():
    cmd = BrakeCommand(kind="APPLY", target_notch=2, phase="B2")
    assert governor_action_for_command(cmd) == "HOLD"


def test_governor_action_for_command_release():
    cmd = BrakeCommand(kind="RELEASE", target_notch=4)
    assert governor_action_for_command(cmd) == "RELEASE"


def test_plan_to_brake_command_apply_b1():
    plan = _plan()
    cmd, _ = plan_to_brake_command(
        plan,
        speed_mph=55.0,
        throttle_notch=0,
        effective_limit=75.0,
        current_notch=4,
    )
    assert cmd is not None
    assert cmd.kind == "APPLY"
    assert cmd.phase == "B1"
    assert cmd.target_notch == 3


def test_plan_to_brake_command_coast_when_throttle():
    plan = _plan()
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
    plan = _plan(dist_start=-80.0, target_speed_mph=50.0)
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
    plan = _plan(
        target_kind="STATION",
        target_speed_mph=0.0,
        distance_m=30.0,
        apply_now=True,
        dist_start=0.0,
        notch="B2",
        handle_notch=2,
    )
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
