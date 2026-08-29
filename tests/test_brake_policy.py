"""Tests de física P1 y policy (cluster / defer) — código TSW, no Dastsc planner."""

from tsw6.braking.v2.physics import (
    MPH_TO_MS,
    apply_zone_margin_m,
    brake_command_apply_zone_m,
    braking_distance_m,
    should_emit_brake_command,
)
from tsw6.braking.v2.plan import UK_SERVICE_PHASES
from tsw6.braking.v2.policy import (
    sequential_limit_stop_feasible,
    should_defer_station_brake,
    should_delay_unified_station_plan,
    should_merge_limit_and_station_plans,
    targets_are_clustered,
)
from tsw6.braking.v2.station_plan import plan_station_service_brake


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
        from tsw6.braking.v2.physics import is_in_brake_action_window

        zone = brake_command_apply_zone_m(speed_mph=55.0, apply_at_remaining_m=900.0)
        assert not is_in_brake_action_window(
            -500.0,
            speed_mph=55.0,
            apply_at_remaining_m=900.0,
        )
        assert -500.0 < -zone
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


class TestStationServiceProfile:
    def test_service_plan_has_b1_b2_b3(self):
        plan = plan_station_service_brake(
            speed_mph=50.0, station_distance_m=800.0)
        assert plan is not None
        assert len(plan.steps) == len(UK_SERVICE_PHASES)
        assert {s.notch for s in plan.steps} == {"B1", "B2", "B3"}
        assert plan.target_kind == "STATION"
        assert plan.target_speed_mph == 0.0

    def test_no_plan_when_already_stopped(self):
        assert plan_station_service_brake(
            speed_mph=0.2, station_distance_m=200.0) is None

    def test_uses_learned_decel(self):
        def predict(handle: int, speed: float, grad: float):
            return {3: 0.35, 2: 0.55, 1: 0.85}.get(handle)

        plain = plan_station_service_brake(
            speed_mph=50.0, station_distance_m=600.0)
        learned = plan_station_service_brake(
            speed_mph=50.0, station_distance_m=600.0, predict_decel=predict)
        assert plain and learned
        assert any(s.using_learned for s in learned.steps)
        b1_plain = next(s for s in plain.steps if s.notch == "B1")
        b1_learned = next(s for s in learned.steps if s.notch == "B1")
        assert b1_learned.distance_m != b1_plain.distance_m


class TestLimitStationPolicy:
    def test_targets_clustered(self):
        assert targets_are_clustered(300, 400) is True
        assert targets_are_clustered(300, 800) is False

    def test_merge_when_sign_before_platform(self):
        assert should_merge_limit_and_station_plans(300, 400) is True
        assert should_merge_limit_and_station_plans(800, 500) is False

    def test_two_phase_when_gap_allows_stop_after_limit(self):
        assert sequential_limit_stop_feasible(
            limit_mph=30.0, limit_dist_m=500.0, station_dist_m=820.0) is True

    def test_unified_stop_when_gap_too_short_after_limit(self):
        assert sequential_limit_stop_feasible(
            limit_mph=55.0, limit_dist_m=400.0, station_dist_m=550.0) is False

    def test_delays_station_at_limit_speed_until_horizon(self):
        assert should_delay_unified_station_plan(
            speed_mph=30.0,
            limit_mph=30.0,
            limit_dist_m=500.0,
            station_dist_m=820.0,
            base_decel=0.8,
        ) is True

    def test_defers_when_outside_service_horizon(self):
        assert should_defer_station_brake(
            speed_mph=55.2, station_dist_m=684.0, base_decel=0.8,
        ) is True

    def test_does_not_defer_inside_service_horizon(self):
        assert should_defer_station_brake(
            speed_mph=30.0, station_dist_m=200.0, base_decel=0.8,
        ) is False
