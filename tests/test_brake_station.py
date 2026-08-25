"""Tests de frenada en estación (puerto Dastsc stationBrake / planBrake STATION)."""

from datetime import datetime

import pytest

from tsw6.braking.v2.planner import (
    DEFAULT_STATION_CFG,
    BrakePlanStep,
    StationBrakeConfig,
    plan_brake,
    plan_brake_for_station,
    plan_station_final_stop,
    plan_station_service_brake,
    schedule_coast_allowance_m,
    schedule_reaction_scale,
    schedule_slack_sec,
    select_station_active_step,
    should_suppress_station_braking_for_departure,
)


class TestScheduleReactionScale:
    def test_reduces_reaction_when_early(self):
        now = datetime(2026, 8, 1, 14, 30, 0)
        early = schedule_reaction_scale(600, 44.7, "14:38", now)  # ~20 m/s
        late = schedule_reaction_scale(600, 44.7, "14:29", now)
        assert early < late
        assert early < 1.0
        assert late > 1.0

    def test_hud_arrival_hhmmss_parses(self):
        from tsw6.braking.v2.planner import normalize_station_eta, parse_eta_minutes

        assert normalize_station_eta("08:18:00") == "8:18"
        assert parse_eta_minutes("08:18:00") == 8 * 60 + 18

class TestStationServiceBrake:
    def test_shorter_reaction_than_speed_limit(self):
        station = plan_station_service_brake(
            speed_mph=44.7, station_distance_m=800.0)
        limit = plan_brake(
            speed_mph=44.7,
            distance_to_target_m=800.0,
            target_speed_mph=0.0,
            target_kind="SPEED_LIMIT",
        )
        assert station is not None and limit is not None
        assert station.reaction_margin_m < limit.reaction_margin_m

    def test_previews_b2_when_early_vs_schedule(self):
        now = datetime(2026, 8, 1, 14, 30, 0)
        plan = plan_station_service_brake(
            speed_mph=44.7,
            station_distance_m=900.0,
            station_eta="14:38",
            now=now,
        )
        assert plan is not None and plan.active_step is not None
        assert plan.active_step.notch == "B2"
        assert plan.active_step.dist_start > 0
        slack = schedule_slack_sec(900, 44.7, "14:38", now)
        assert slack is not None and slack > 30
        assert schedule_coast_allowance_m(900, 44.7, "14:38", now) > 100
        assert schedule_coast_allowance_m(80, 44.7, "14:38", now) == 0

    def test_delays_brake_point_when_early(self):
        now = datetime(2026, 8, 1, 14, 30, 0)
        early = plan_station_service_brake(
            speed_mph=44.7, station_distance_m=900.0,
            station_eta="14:38", now=now)
        plain = plan_station_service_brake(
            speed_mph=44.7, station_distance_m=900.0)
        assert early and plain
        b2_early = next(s for s in early.steps if s.notch == "B2")
        b2_plain = next(s for s in plain.steps if s.notch == "B2")
        assert b2_early.dist_start > b2_plain.dist_start
        assert early.reaction_margin_m < plain.reaction_margin_m


class TestStationFinalStop:
    def test_final_stop_at_platform_zero(self):
        plan = plan_station_final_stop(
            speed_mph=6.7, station_distance_m=0.0)
        assert plan is not None
        assert plan.active_step is not None
        assert plan.active_step.apply_now is True
        assert plan.active_step.notch == "B2"

    def test_no_final_stop_when_departing_fast(self):
        assert plan_station_final_stop(
            speed_mph=27.0, station_distance_m=0.0) is None

    def test_no_final_stop_stale_ocr_creep(self):
        cfg = DEFAULT_STATION_CFG
        assert plan_station_final_stop(
            speed_mph=5.6, station_distance_m=48.0, throttle_notch=1) is None
        assert plan_brake_for_station(
            speed_mph=5.6,
            station_distance_m=48.0,
            throttle_notch=1,
            cfg=cfg,
        ) is None

    def test_no_final_stop_leaving_terminus_with_power(self):
        assert plan_station_final_stop(
            speed_mph=7.5, station_distance_m=0.0, throttle_notch=1) is None
        assert plan_brake_for_station(
            speed_mph=7.5,
            station_distance_m=0.0,
            throttle_notch=1,
            station_traveled_m=0.0,
        ) is None

    def test_within_extended_platform_zone(self):
        cfg = StationBrakeConfig(final_stop_max_distance_m=35.0)
        plan = plan_station_final_stop(
            speed_mph=4.5, station_distance_m=29.0, cfg=cfg)
        assert plan is not None
        assert plan.active_step is not None
        assert plan.active_step.apply_now is True


class TestStationSuppression:
    def test_short_turnaround_anchor(self):
        assert plan_brake_for_station(
            speed_mph=13.4,
            station_distance_m=97.0,
            throttle_notch=1,
            station_anchor_m=129.0,
            station_traveled_m=30.0,
        ) is None

    def test_phantom_station_after_turnaround(self):
        assert plan_brake_for_station(
            speed_mph=0.0,
            station_distance_m=97.0,
            station_traveled_m=0.0,
        ) is None
        assert plan_brake_for_station(
            speed_mph=8.9,
            station_distance_m=85.0,
            throttle_notch=1,
            station_traveled_m=25.0,
        ) is None

    def test_genuine_approach_at_97m(self):
        plan = plan_brake_for_station(
            speed_mph=33.6,
            station_distance_m=97.0,
            station_traveled_m=2800.0,
            station_eta="14:38",
        )
        assert plan is not None

    def test_suppress_flag_matches_departure(self):
        assert should_suppress_station_braking_for_departure(
            speed_mph=13.4,
            station_distance_m=97.0,
            throttle_notch=1,
            station_anchor_m=129.0,
            station_traveled_m=30.0,
        )


class TestSelectStationActiveStep:
    def _step(self, notch: str, dist_start: float) -> BrakePlanStep:
        handles = {"B1": 3, "B2": 2, "B3": 1}
        return BrakePlanStep(
            notch=notch,
            handle_notch=handles[notch],
            phase="1",
            distance_m=200.0,
            apply_at_remaining_m=240.0,
            dist_start=dist_start,
            meters_until_action_m=max(0.0, dist_start),
            apply_now=dist_start <= 0,
        )

    def test_prefers_strongest_near_station(self):
        steps = [self._step("B3", 8), self._step("B2", 12), self._step("B1", 18)]
        active = select_station_active_step(steps, 12.0, 300.0)
        assert active is not None
        assert active.notch == "B3"

    def test_b2_default_when_due(self):
        steps = [
            self._step("B3", -40),
            self._step("B2", -5),
            self._step("B1", -80),
        ]
        active = select_station_active_step(steps, 18.0, 600.0)
        assert active is not None
        assert active.notch == "B2"
