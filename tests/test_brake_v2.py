"""Tests frenado v2."""

from tsw6.autopilot.control_actions import BRAKE, EMERGENCY
from tsw6.braking.v2.objectives import check_p1_emergency, is_red_signal_aspect
from tsw6.braking.v2.limit_brake import (
    LimitBrakeState,
    _apply_notch_hysteresis,
    evaluate_limit_brake,
)
from tsw6.braking.v2.physics import brake_command_apply_zone_m
from tsw6.braking.v2.command import BrakeTargetResult
from tsw6.braking.v2.policy import select_urgent_target


def _apply_zone(speed_mph: float, dist_start: float, distance_m: float = 400.0) -> float:
    apply_at = distance_m - dist_start
    return brake_command_apply_zone_m(
        speed_mph=speed_mph,
        apply_at_remaining_m=apply_at,
    )


class TestEmergencyV2:
    def test_no_emergency_far_from_station(self):
        assert check_p1_emergency(
            target_kind="STATION",
            speed_mph=40.0,
            urgent_dist_m=500.0,
            base_decel=0.8,
            gradient_pct=0.0,
            brake_transition_s=0.5,
            accel_ms2=None,
        ) is None

    def test_station_critical_close_fast(self):
        result = check_p1_emergency(
            target_kind="STATION",
            speed_mph=45.0,
            urgent_dist_m=30.0,
            base_decel=0.8,
            gradient_pct=0.0,
            brake_transition_s=0.5,
            accel_ms2=None,
        )
        assert result is not None
        action, eff, cmd = result
        assert action in (BRAKE, EMERGENCY)
        assert eff == 0.0
        assert "STATION" in cmd.reason

    def test_no_emergency_creep_near_platform(self):
        """8 mph a 40 m: s_parada corta; no P1 por metros fijos."""
        assert check_p1_emergency(
            target_kind="STATION",
            speed_mph=8.0,
            urgent_dist_m=40.0,
            base_decel=0.8,
            gradient_pct=0.0,
            brake_transition_s=0.5,
            accel_ms2=None,
        ) is None

    def test_red_signal_aspect(self):
        assert is_red_signal_aspect("DANGER")
        assert is_red_signal_aspect("red")
        assert not is_red_signal_aspect("CLEAR")


class TestLimitBrakeV2:
    def test_latches_decel_on_new_limit(self):
        state = LimitBrakeState()
        r1 = evaluate_limit_brake(
            state,
            speed_mph=60.0,
            limit_mph=55.0,
            distance_m=800.0,
            gradient_pct=0.0,
        )
        assert r1 is not None
        assert state.latch is not None
        assert state.latch.limit_mph == 55.0
        assert state.latch.latched_speed_mph == 60.0
        assert 3 in state.latch.decel_by_handle

    def test_60_to_55_prefers_weak_notch_far(self):
        state = LimitBrakeState()
        r = evaluate_limit_brake(
            state,
            speed_mph=60.0,
            limit_mph=55.0,
            distance_m=1200.0,
            gradient_pct=0.0,
        )
        assert r is not None
        assert r.phase in ("B1", "B2")
        assert r.dist_start > 0

    def test_apply_at_grows_when_speed_rises(self):
        """Reacción y s con v actual: 55→58 abre más ventana, no queda latch @55."""
        state = LimitBrakeState()
        r1 = evaluate_limit_brake(
            state,
            speed_mph=55.3,
            limit_mph=55.0,
            distance_m=800.0,
            gradient_pct=0.0,
        )
        r2 = evaluate_limit_brake(
            state,
            speed_mph=58.0,
            limit_mph=55.0,
            distance_m=800.0,
            gradient_pct=0.0,
        )
        assert r1 and r2
        apply1 = r1.distance_m - r1.dist_start
        apply2 = r2.distance_m - r2.dist_start
        assert apply2 > apply1
        assert r2.phase == "B1"

    def test_downhill_starts_earlier_not_stronger_display(self):
        """Bajada: más s, mismo B1 lejos; no mostrar B3 a 400 m."""
        state_flat = LimitBrakeState()
        flat = evaluate_limit_brake(
            state_flat,
            speed_mph=60.0,
            limit_mph=55.0,
            distance_m=400.0,
            gradient_pct=0.0,
        )
        state_hill = LimitBrakeState()
        hill = evaluate_limit_brake(
            state_hill,
            speed_mph=60.0,
            limit_mph=55.0,
            distance_m=400.0,
            gradient_pct=-1.0,
        )
        assert flat and hill
        assert hill.phase == "B1"
        assert flat.phase == "B1"
        assert hill.dist_start <= flat.dist_start

    def test_committed_notch_does_not_weaken_in_apply_zone(self):
        state = LimitBrakeState()
        state.committed_handle = 2
        state.committed_phase = "B2"
        handle, phase = _apply_notch_hysteresis(
            state,
            handle=3,
            phase="B1",
            dist_start=50.0,
            apply_now=True,
            apply_zone_m=_apply_zone(58.0, 50.0),
            speed_mph=58.0,
            limit_mph=55.0,
        )
        assert handle == 2
        assert phase == "B2"

    def test_committed_notch_downgrades_with_margin(self):
        state = LimitBrakeState()
        state.committed_handle = 1
        state.committed_phase = "B3"
        zone = _apply_zone(58.0, 90.0)
        handle, phase = _apply_notch_hysteresis(
            state,
            handle=3,
            phase="B1",
            dist_start=90.0,
            apply_now=False,
            apply_zone_m=zone,
            speed_mph=58.0,
            limit_mph=55.0,
        )
        assert 90.0 > zone
        assert handle == 2
        assert phase == "B2"

    def test_committed_notch_downgrades_at_target_speed(self):
        state = LimitBrakeState()
        state.committed_handle = 1
        state.committed_phase = "B3"
        handle, phase = _apply_notch_hysteresis(
            state,
            handle=3,
            phase="B1",
            dist_start=5.0,
            apply_now=True,
            apply_zone_m=_apply_zone(54.5, 5.0),
            speed_mph=54.5,
            limit_mph=55.0,
        )
        assert handle == 2
        assert phase == "B2"

    def test_committed_notch_escalates_one_step(self):
        """B1 pedido B3 → B2 en este tick, no B3 de golpe."""
        state = LimitBrakeState()
        state.committed_handle = 3
        state.committed_phase = "B1"
        handle, phase = _apply_notch_hysteresis(
            state,
            handle=1,
            phase="B3",
            dist_start=-20.0,
            apply_now=True,
            apply_zone_m=_apply_zone(58.0, -20.0),
            speed_mph=58.0,
            limit_mph=55.0,
        )
        assert handle == 2
        assert phase == "B2"


class TestPriorityV2:
    def _r(
        self,
        kind: str,
        dist: float,
        dist_start: float,
        target_mph: float = 55.0,
    ) -> BrakeTargetResult:
        return BrakeTargetResult(
            target_kind=kind,  # type: ignore[arg-type]
            distance_m=dist,
            target_speed_mph=target_mph if kind == "SPEED_LIMIT" else 0.0,
            handle_notch=2,
            phase="B2",
            dist_start=dist_start,
            apply_now=dist_start <= 0,
        )

    def test_signal_over_limit_when_ahead(self):
        limit = self._r("SPEED_LIMIT", 500.0, 80.0)
        signal = self._r("SIGNAL", 480.0, 60.0)
        picked = select_urgent_target(
            [limit, signal],
            limit_dist_m=500.0,
            signal_dist_m=480.0,
        )
        assert picked is signal

    def test_station_wins_unified_stop_over_limit(self):
        """A 54 mph, paso estación aún no vencido: el cartel sigue mandando el momento."""
        limit = self._r("SPEED_LIMIT", 400.0, 50.0, target_mph=55.0)
        station = self._r("STATION", 550.0, 30.0)
        picked = select_urgent_target(
            [limit, station],
            speed_mph=54.0,
            limit_mph=55.0,
            limit_dist_m=400.0,
            station_dist_m=550.0,
        )
        assert picked is limit

    def test_limit_wins_unified_overspeed_before_station_window(self):
        """Unificado con exceso de velocidad: timing del 55, no B1 de andén."""
        limit = self._r("SPEED_LIMIT", 400.0, 50.0, target_mph=55.0)
        station = self._r("STATION", 550.0, 30.0)
        picked = select_urgent_target(
            [limit, station],
            speed_mph=60.0,
            limit_mph=55.0,
            limit_dist_m=400.0,
            station_dist_m=550.0,
        )
        assert picked is limit

    def test_limit_first_when_two_phase_ok(self):
        """Cartel a 400 m, andén a 820 m: sí cabe frenar al cartel y luego parar."""
        limit = self._r("SPEED_LIMIT", 400.0, 50.0, target_mph=30.0)
        station = self._r("STATION", 820.0, 200.0)
        picked = select_urgent_target(
            [limit, station],
            speed_mph=60.0,
            limit_mph=30.0,
            limit_dist_m=400.0,
            station_dist_m=820.0,
        )
        assert picked is limit

    def test_limit_wins_unified_overspeed_station_far(self):
        """58 mph, uni=Y, andén sin plan: cartel 55 debe ganar (Four Oaks)."""
        limit = self._r("SPEED_LIMIT", 1500.0, 80.0, target_mph=55.0)
        station = self._r("STATION", 1750.0, 800.0)
        picked = select_urgent_target(
            [limit, station],
            speed_mph=58.0,
            limit_mph=55.0,
            limit_dist_m=1500.0,
            station_dist_m=1750.0,
        )
        assert picked is limit

    def test_station_wins_when_plan_late_in_unified_cluster(self):
        """Unificado: paso estación 'tarde' no gana al cartel si el 55 sigue delante."""
        limit = self._r("SPEED_LIMIT", 400.0, 80.0, target_mph=55.0)
        station = self._r("STATION", 550.0, -300.0)
        picked = select_urgent_target(
            [limit, station],
            speed_mph=60.0,
            limit_mph=55.0,
            limit_dist_m=400.0,
            station_dist_m=550.0,
        )
        assert picked is limit

    def test_station_wins_when_signal_slightly_after(self):
        station = self._r("STATION", 300.0, 80.0)
        signal = self._r("SIGNAL", 340.0, 60.0)
        picked = select_urgent_target(
            [station, signal],
            station_dist_m=300.0,
            signal_dist_m=340.0,
        )
        assert picked is station

    def test_ahead_and_urgency_sort(self):
        limit = self._r("SPEED_LIMIT", 200.0, 100.0)
        station = self._r("STATION", 800.0, -20.0)
        picked = select_urgent_target([limit, station])
        assert picked is limit


class TestStationBrakeV2:
    def test_far_station_not_a_candidate(self):
        from tsw6.braking.v2.objectives import evaluate_station_brake

        result = evaluate_station_brake(
            speed_mph=32.0,
            station_distance_m=10887.0,
            base_decel=0.8,
            throttle_notch=3,
        )
        assert result is None

    def test_no_coast_throttle_when_station_far(self):
        target = BrakeTargetResult(
            target_kind="STATION",
            distance_m=10887.0,
            target_speed_mph=0.0,
            handle_notch=2,
            phase="B2",
            dist_start=10756.0,
            apply_now=False,
        )
        assert target.to_brake_command(throttle_notch=3, current_notch=6) is None

    def test_speed_limit_coasts_before_apply_window(self):
        target = BrakeTargetResult(
            target_kind="SPEED_LIMIT",
            distance_m=1120.0,
            target_speed_mph=55.0,
            handle_notch=3,
            phase="B1",
            dist_start=1058.0,
            apply_now=False,
        )
        cmd = target.to_brake_command(
            throttle_notch=2, current_notch=6, speed_mph=55.3,
        )
        assert cmd is not None
        assert cmd.kind == "COAST_THROTTLE"
        assert cmd.target_notch == 4

    def test_speed_limit_overspeed_applies_outside_window(self):
        target = BrakeTargetResult(
            target_kind="SPEED_LIMIT",
            distance_m=700.0,
            target_speed_mph=55.0,
            handle_notch=3,
            phase="B1",
            dist_start=580.0,
            apply_now=False,
        )
        cmd = target.to_brake_command(
            throttle_notch=0, current_notch=4, speed_mph=56.3,
        )
        assert cmd is not None
        assert cmd.kind == "APPLY"
        assert cmd.target_notch == 3

    def test_speed_limit_releases_when_in_band(self):
        target = BrakeTargetResult(
            target_kind="SPEED_LIMIT",
            distance_m=429.0,
            target_speed_mph=55.0,
            handle_notch=3,
            phase="B1",
            dist_start=350.0,
            apply_now=False,
        )
        cmd = target.to_brake_command(
            throttle_notch=0, current_notch=3, speed_mph=55.2,
        )
        assert cmd is not None
        assert cmd.kind == "RELEASE"
        assert cmd.target_notch == 4
