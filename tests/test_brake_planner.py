"""Tests de brake_planner (puerto Dastsc)."""

import pytest

from tsw6.autopilot.control_actions import BRAKE, COAST
from tsw6.braking.v2.physics import (
    MPH_TO_MS,
    apply_zone_margin_m,
    brake_command_apply_zone_m,
    braking_distance_m,
    should_emit_brake_command,
)
from tsw6.braking.v2.planner import (
    UK_SERVICE_PHASES,
    plan_brake,
    plan_for_approach_targets,
    plan_for_speed_limits,
    plan_to_governor_action,
    resolve_chained_limit_target,
    select_urgent_brake_plan,
    select_urgent_plan,
    sequential_limit_stop_feasible,
    should_merge_limit_and_station_plans,
    should_delay_unified_station_plan,
    targets_are_clustered,
)


class TestBrakingPhysics:
    def test_braking_distance_basic(self):
        d = braking_distance_m(20.0, 10.0, 0.8)
        assert 150 < d < 250

    def test_apply_zone_scales_with_speed(self):
        low = apply_zone_margin_m(5.0, 200.0)
        high = apply_zone_margin_m(25.0, 200.0)
        assert high > low

    def test_should_emit_uses_physics_zone_not_fixed_60m(self):
        """60 mph: zona ~67 m; perfil a 65 m debe emitir aunque apply_now sea False."""
        zone = brake_command_apply_zone_m(speed_mph=60.0, apply_at_remaining_m=200.0)
        assert zone > 60.0
        assert should_emit_brake_command(
            apply_now=False,
            dist_start=65.0,
            speed_mph=60.0,
            apply_at_remaining_m=200.0,
        )
        assert not should_emit_brake_command(
            apply_now=False,
            dist_start=zone + 5.0,
            speed_mph=60.0,
            apply_at_remaining_m=200.0,
        )

    def test_brake_command_zone_from_dist_start(self):
        speed_mph = 52.0
        distance_m = 329.0
        dist_start = 41.0
        apply_at = distance_m - dist_start
        zone = brake_command_apply_zone_m(
            speed_mph=speed_mph,
            distance_to_target_m=distance_m,
            dist_start=dist_start,
        )
        assert zone == apply_zone_margin_m(speed_mph * MPH_TO_MS, apply_at)
        assert should_emit_brake_command(
            apply_now=False,
            dist_start=dist_start,
            speed_mph=speed_mph,
            distance_to_target_m=distance_m,
        )

    def test_symmetric_zone_rejects_far_late_plan(self):
        """Plan «tarde» lejos del objetivo: no ventana de prioridad estación."""
        from tsw6.braking.v2.physics import is_in_brake_action_window

        zone = brake_command_apply_zone_m(speed_mph=55.0, apply_at_remaining_m=900.0)
        assert not is_in_brake_action_window(
            -500.0,
            speed_mph=55.0,
            apply_at_remaining_m=900.0,
        )
        assert -500.0 < -zone
        # Pero sí emitir comando si aún dentro del envelope de frenado
        assert should_emit_brake_command(
            apply_now=True,
            dist_start=-500.0,
            speed_mph=55.0,
            distance_to_target_m=400.0,
            apply_at_remaining_m=900.0,
        )

    def test_is_in_apply_zone_symmetric(self):
        from tsw6.braking.v2.physics import is_in_apply_zone

        assert is_in_apply_zone(40.0, 65.0)
        assert is_in_apply_zone(-40.0, 65.0)
        assert not is_in_apply_zone(80.0, 65.0)
        assert not is_in_apply_zone(-80.0, 65.0)


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
        assert action == COAST

    def test_brake_when_no_throttle(self):
        plan = plan_brake(
            speed_mph=55.0, distance_to_target_m=200.0, target_speed_mph=30.0)
        assert plan and plan.active_step
        step = plan.active_step
        # Dentro del envelope tarde: debe emitir BRAKE aunque fuera de ±zona
        assert should_emit_brake_command(
            apply_now=step.apply_now,
            dist_start=step.dist_start,
            speed_mph=55.0,
            distance_to_target_m=plan.distance_to_target_m,
            apply_at_remaining_m=step.apply_at_remaining_m,
        )
        action, _ = plan_to_governor_action(
            plan, speed_mph=55.0, throttle_notch=0, effective_limit=60.0)
        assert action == BRAKE


class TestLimitQueue:
    def test_plan_for_speed_limits(self):
        limits = [
            {"limit_mph": 50.0, "distance_m": 1200.0},
            {"limit_mph": 30.0, "distance_m": 600.0},
        ]
        plan = plan_for_speed_limits(55.0, limits, 60.0, 0.0, 0.8)
        assert plan is not None
        assert plan.target_speed_mph == 30.0


class TestClusteredLimitStation:
    """Paridad Dastsc: cartel 55 antes del andén."""

    def test_targets_clustered(self):
        assert targets_are_clustered(300, 400) is True
        assert targets_are_clustered(300, 800) is False

    def test_merge_when_sign_before_platform(self):
        assert should_merge_limit_and_station_plans(300, 400) is True
        assert should_merge_limit_and_station_plans(800, 500) is False

    def test_prefers_limit_plan_when_55_before_stop(self):
        """60 mph, cartel 55 a 500 m, estación a 800 m → parada unificada (gap corto)."""
        limits = [{"limit_mph": 55.0, "distance_m": 500.0}]
        result = plan_for_approach_targets(
            60.0, limits, 800.0, 60.0, 0.0, 0.8, station_name="Alden")
        assert result is not None
        assert result.active.target_kind == "STATION"
        assert result.follow_up is None
        assert result.chain is not None
        assert result.chain.unified_stop is True
        assert result.chain.phase == 2

    def test_two_phase_when_gap_allows_stop_after_limit(self):
        """60→30 mph con andén a +320 m: sí cabe frenar al cartel y luego parar."""
        limits = [{"limit_mph": 30.0, "distance_m": 500.0}]
        assert sequential_limit_stop_feasible(
            limit_mph=30.0, limit_dist_m=500.0, station_dist_m=820.0) is True
        result = plan_for_approach_targets(
            60.0, limits, 820.0, 60.0, 0.0, 0.8, station_name="Alden")
        assert result is not None
        assert result.active.target_kind == "SPEED_LIMIT"
        assert result.active.target_speed_mph == 30.0
        assert result.follow_up is not None
        assert result.follow_up.target_kind == "STATION"
        assert result.chain is not None
        assert result.chain.clustered is True
        assert result.chain.phase == 1
        assert result.chain.unified_stop is False

    def test_unified_stop_when_gap_too_short_after_limit(self):
        """60→55 con andén a +150 m: no hay margen para soltar y parar."""
        limits = [{"limit_mph": 55.0, "distance_m": 400.0}]
        assert sequential_limit_stop_feasible(
            limit_mph=55.0, limit_dist_m=400.0, station_dist_m=550.0) is False
        result = plan_for_approach_targets(
            60.0, limits, 550.0, 60.0, 0.0, 0.8, station_name="Alden")
        assert result is not None
        assert result.active.target_kind == "STATION"
        assert result.follow_up is None
        assert result.chain is not None
        assert result.chain.unified_stop is True
        assert result.chain.phase == 2

    def test_delays_station_at_limit_speed_until_near_sign(self):
        """55 mph, cartel a 700 m, andén a 987 m — coast hasta ~200 m del cartel."""
        limits = [{"limit_mph": 55.0, "distance_m": 700.0}]
        assert should_delay_unified_station_plan(
            speed_mph=55.0,
            limit_mph=55.0,
            limit_dist_m=700.0,
            station_dist_m=987.0,
        ) is True
        far = plan_for_approach_targets(
            55.0, limits, 987.0, 60.0, 0.0, 0.8, station_name="Four Oaks")
        assert far is None
        near = plan_for_approach_targets(
            55.0, limits, 487.0, 60.0, 0.0, 0.8, station_name="Four Oaks")
        assert near is not None
        assert near.active.target_kind == "STATION"

    def test_two_phase_chain_uses_follow_up_after_limit(self):
        limits = [{"limit_mph": 30.0, "distance_m": 500.0}]
        result = plan_for_approach_targets(
            60.0, limits, 820.0, 60.0, 0.0, 0.8, station_name="Alden")
        assert result is not None
        phase2 = plan_for_approach_targets(
            30.0, limits, 770.0, 60.0, 0.0, 0.8,
            station_name="Alden", limit_phase_done=True)
        assert phase2 is not None
        assert phase2.active.target_kind == "STATION"
        assert phase2.follow_up is None
        assert phase2.chain is not None
        assert phase2.chain.phase == 2

    def test_resolve_chained_limit_target(self):
        limits = [
            {"limit_mph": 75.0, "distance_m": 400.0},
            {"limit_mph": 25.0, "distance_m": 600.0},
        ]
        tgt = resolve_chained_limit_target(limits)
        assert tgt is not None
        assert tgt["limit_mph"] == 25.0

    def test_select_urgent_drops_station_when_merged(self):
        limit_plan = plan_brake(
            speed_mph=60.0, distance_to_target_m=500.0, target_speed_mph=55.0)
        station_plan = plan_brake(
            speed_mph=60.0, distance_to_target_m=800.0, target_speed_mph=0.0,
            target_kind="STATION")
        assert limit_plan and station_plan
        selected = select_urgent_brake_plan(
            [limit_plan, station_plan],
            limit_dist_m=500.0,
            station_dist_m=800.0,
        )
        assert selected is not None
        assert selected.target_kind == "SPEED_LIMIT"


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
