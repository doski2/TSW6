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
from tsw6.braking.v2.limit_brake import LimitBrakeState, evaluate_limit_brake


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
        speed_mph=50.5,
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


def test_no_release_parked_at_scenario_start():
    """Arranque: parado con freno (notch=1) y cartel lejos — no soltar a neutro."""
    cmd = resolve_release_command(
        speed_mph=0.0,
        handle_notch=1,
        effective_limit=20.0,
        next_limit_mph=45.0,
        distance_next_m=271.0,
        gradient_pct=0.2,
    )
    assert cmd is None


def test_release_at_limit_speed_on_downhill():
    """Bajada: soltar en el cartel (no mantener B3 hasta casi parado)."""
    cmd = resolve_release_command(
        speed_mph=45.0,
        handle_notch=1,
        effective_limit=55.0,
        next_limit_mph=45.0,
        distance_next_m=200.0,
        gradient_pct=-1.0,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"
    assert cmd.target_notch == 4


def test_downhill_containment_b1_before_penalty():
    """55.4 en cartel 55 bajada -1% → B1 (muesca servicio 1)."""
    state = LimitBrakeState()
    r = evaluate_limit_brake(
        state,
        speed_mph=55.4,
        limit_mph=55.0,
        distance_m=80.0,
        gradient_pct=-1.0,
    )
    assert r is not None
    assert r.apply_now
    assert r.phase == "B1"


def test_downhill_containment_b2_near_ceiling():
    """55.85: primer tick B1, segundo B2 (no saltar)."""
    state = LimitBrakeState()
    r1 = evaluate_limit_brake(
        state,
        speed_mph=55.85,
        limit_mph=55.0,
        distance_m=80.0,
        gradient_pct=-1.0,
    )
    assert r1 is not None
    assert r1.phase == "B1"
    r2 = evaluate_limit_brake(
        state,
        speed_mph=55.85,
        limit_mph=55.0,
        distance_m=80.0,
        gradient_pct=-1.0,
    )
    assert r2 is not None
    assert r2.phase == "B2"


def test_downhill_containment_after_limit():
    """Repunte leve en bajada → B1 inmediato, no esperar dist_start."""
    state = LimitBrakeState()
    r = evaluate_limit_brake(
        state,
        speed_mph=45.5,
        limit_mph=45.0,
        distance_m=80.0,
        gradient_pct=-1.0,
    )
    assert r is not None
    assert r.apply_now
    assert r.phase == "B1"
    assert "Contención bajada" in r.detail


def test_far_approach_uses_full_plan_not_containment():
    """57 mph a 800 m del cartel: plan de aproximación, no contención."""
    state = LimitBrakeState()
    r = evaluate_limit_brake(
        state,
        speed_mph=57.0,
        limit_mph=55.0,
        distance_m=800.0,
        gradient_pct=-1.0,
    )
    assert r is not None
    assert "Contención bajada" not in r.detail


def test_containment_skipped_at_1km():
    """C.3b: 56 mph a 1018 m → plan, no B2 de contención."""
    state = LimitBrakeState()
    r = evaluate_limit_brake(
        state,
        speed_mph=56.0,
        limit_mph=55.0,
        distance_m=1018.0,
        gradient_pct=-1.0,
    )
    if r is not None:
        assert "Contención bajada" not in (r.detail or "")


def test_coast_at_limit_on_downhill_no_brake():
    """En el cartel en bajada → sin plan (coast)."""
    state = LimitBrakeState()
    r = evaluate_limit_brake(
        state,
        speed_mph=45.0,
        limit_mph=45.0,
        distance_m=300.0,
        gradient_pct=-1.0,
    )
    assert r is None


def test_containment_inactive_during_station_approach_speed():
    """Frenada final estación (spd << cartel): sin contención de límite."""
    state = LimitBrakeState()
    r = evaluate_limit_brake(
        state,
        speed_mph=25.0,
        limit_mph=55.0,
        distance_m=50.0,
        gradient_pct=-1.0,
    )
    assert r is None


def test_release_downhill_coordinator():
    coord = BrakeCoordinatorV2()
    action, _ = coord.evaluate(
        speed_mph=45.0,
        next_limit_mph=45.0,
        distance_next_m=250.0,
        effective_limit=55.0,
        gradient_pct=-1.0,
        acceleration_ms2=None,
        throttle_notch=0,
        handle_notch=1,
        base_decel_ms2=0.80,
        station_distance_m=2200.0,
        station_name="Sutton Coldfield",
    )
    assert action == "RELEASE"
    assert coord.last_brake_command is not None
    assert coord.last_brake_command.kind == "RELEASE"

    coord = BrakeCoordinatorV2()
    action, _ = coord.evaluate(
        speed_mph=0.0,
        next_limit_mph=45.0,
        distance_next_m=271.0,
        effective_limit=20.0,
        gradient_pct=0.2,
        acceleration_ms2=None,
        throttle_notch=0,
        handle_notch=1,
        base_decel_ms2=0.80,
        station_distance_m=11204.0,
        station_name="Four Oaks",
    )
    assert action != "RELEASE"
