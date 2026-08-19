"""Tests de brake_planner (puerto Dastsc)."""

import pytest

from brake_planner import (
    UK_SERVICE_PHASES,
    apply_zone_margin_m,
    braking_distance_m,
    plan_brake,
    plan_for_speed_limits,
    plan_to_governor_action,
    select_urgent_plan,
)


class TestBrakingPhysics:
    def test_braking_distance_basic(self):
        d = braking_distance_m(20.0, 10.0, 0.8)
        assert 150 < d < 250

    def test_apply_zone_scales_with_speed(self):
        low = apply_zone_margin_m(5.0, 200.0)
        high = apply_zone_margin_m(25.0, 200.0)
        assert high > low


class TestPlanBrake:
    def test_plan_has_steps(self):
        plan = plan_brake(
            speed_mph=60.0,
            distance_to_target_m=800.0,
            target_speed_mph=30.0,
        )
        assert plan is not None
        assert len(plan.steps) == len(UK_SERVICE_PHASES)
        assert plan.active_step is not None

    def test_no_plan_when_already_at_target(self):
        assert plan_brake(
            speed_mph=30.0,
            distance_to_target_m=500.0,
            target_speed_mph=30.0,
        ) is None

    def test_urgent_picks_closest(self):
        p_far = plan_brake(
            speed_mph=50.0, distance_to_target_m=2000.0, target_speed_mph=40.0)
        p_near = plan_brake(
            speed_mph=50.0, distance_to_target_m=400.0, target_speed_mph=25.0)
        assert p_far and p_near
        urgent = select_urgent_plan([p_far, p_near])
        assert urgent is p_near


class TestGovernorAction:
    def test_coast_when_throttle_active(self):
        plan = plan_brake(
            speed_mph=55.0, distance_to_target_m=300.0, target_speed_mph=30.0)
        assert plan and plan.active_step
        plan.active_step.apply_now = True
        action, _ = plan_to_governor_action(
            plan, speed_mph=55.0, throttle_notch=2, effective_limit=60.0)
        assert action == "COAST"

    def test_brake_when_no_throttle(self):
        plan = plan_brake(
            speed_mph=55.0, distance_to_target_m=200.0, target_speed_mph=30.0)
        assert plan and plan.active_step
        plan.active_step.apply_now = True
        action, _ = plan_to_governor_action(
            plan, speed_mph=55.0, throttle_notch=0, effective_limit=60.0)
        assert action in ("BRAKE", "HARDBRAKE")


class TestLimitQueue:
    def test_plan_for_speed_limits(self):
        limits = [
            {"limit_mph": 50.0, "distance_m": 1200.0},
            {"limit_mph": 30.0, "distance_m": 600.0},
        ]
        plan = plan_for_speed_limits(55.0, limits, 60.0, 0.0, 0.8)
        assert plan is not None
        assert plan.target_speed_mph == 30.0


class TestLearnedDecel:
    def test_plan_uses_learned_decel(self):
        def predict(handle: int, speed: float, grad: float):
            return {3: 0.35, 2: 0.55, 1: 0.85}.get(handle)

        plan_default = plan_brake(
            speed_mph=50.0, distance_to_target_m=600.0, target_speed_mph=30.0)
        plan_learned = plan_brake(
            speed_mph=50.0, distance_to_target_m=600.0, target_speed_mph=30.0,
            predict_decel=predict)
        assert plan_default and plan_learned
        assert any(s.using_learned for s in plan_learned.steps)
        b1_default = next(s for s in plan_default.steps if s.notch == "B1")
        b1_learned = next(s for s in plan_learned.steps if s.notch == "B1")
        assert b1_learned.distance_m != b1_default.distance_m
