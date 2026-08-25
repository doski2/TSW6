"""Tests BrakeCoordinatorV2 — orquestación P1 v2."""

from typing import Optional

from tsw6.autopilot.control_actions import BRAKE, EMERGENCY
from tsw6.braking.v2.coordinator import BrakeCoordinatorV2


def _coord() -> BrakeCoordinatorV2:
    return BrakeCoordinatorV2()


def _eval(
    coord: BrakeCoordinatorV2,
    *,
    speed_mph: float = 60.0,
    next_limit_mph: Optional[float] = 55.0,
    distance_next_m: Optional[float] = 400.0,
    effective_limit: float = 60.0,
    gradient_pct: float = 0.0,
    throttle_notch: int = 0,
    handle_notch: int = 2,
    base_decel_ms2: float = 0.8,
    station_distance_m: Optional[float] = None,
    station_name: Optional[str] = None,
    signal_distance_m: Optional[float] = None,
    signal_aspect: Optional[str] = None,
):
    return coord.evaluate(
        speed_mph=speed_mph,
        next_limit_mph=next_limit_mph,
        distance_next_m=distance_next_m,
        effective_limit=effective_limit,
        gradient_pct=gradient_pct,
        throttle_notch=throttle_notch,
        handle_notch=handle_notch,
        base_decel_ms2=base_decel_ms2,
        station_distance_m=station_distance_m,
        station_name=station_name,
        signal_distance_m=signal_distance_m,
        signal_aspect=signal_aspect,
    )


class TestCoordinatorRelease:
    def test_release_at_limit_speed(self):
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=50.2,
            next_limit_mph=50.0,
            distance_next_m=200.0,
            effective_limit=75.0,
            handle_notch=2,
        )
        assert action == "RELEASE"
        assert coord.last_brake_command is not None
        assert coord.last_brake_command.kind == "RELEASE"
        assert coord.last_debug == "RELEASE→NEU"

    def test_releases_when_stopped_far_from_platform_marker(self):
        """Parada telemetría lejos del andén pero spd≈0 — Four Oaks."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=0.5,
            next_limit_mph=55.0,
            distance_next_m=392.0,
            effective_limit=60.0,
            gradient_pct=-1.0,
            handle_notch=1,
            station_distance_m=654.0,
            station_name="Four Oaks",
        )
        assert action == "RELEASE"
        assert coord.last_brake_command is not None
        assert coord.last_brake_command.kind == "RELEASE"

    def test_no_release_when_too_fast_for_limit(self):
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=58.0,
            next_limit_mph=50.0,
            distance_next_m=200.0,
            effective_limit=75.0,
            handle_notch=2,
        )
        assert action != "RELEASE"


class TestCoordinatorUnifiedStop:
    def test_releases_at_limit_speed_in_unified_cluster(self):
        """60→55 con andén cercano: soltar en cartel y coast hacia andén."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=54.0,
            next_limit_mph=55.0,
            distance_next_m=400.0,
            effective_limit=60.0,
            handle_notch=2,
            station_distance_m=550.0,
        )
        assert action == "RELEASE"
        assert coord.last_brake_command is not None
        assert coord.last_brake_command.kind == "RELEASE"

    def test_blocks_release_while_above_limit_in_unified_cluster(self):
        """Parada unificada: no soltar si aún se supera el cartel."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=58.0,
            next_limit_mph=55.0,
            distance_next_m=400.0,
            effective_limit=60.0,
            handle_notch=2,
            station_distance_m=550.0,
        )
        assert action != "RELEASE"

    def test_delays_station_brake_at_limit_speed_unified(self):
        """55 mph, cartel lejos: coast sin re-aplicar B1 de estación."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=55.0,
            next_limit_mph=55.0,
            distance_next_m=700.0,
            effective_limit=60.0,
            handle_notch=4,
            station_distance_m=987.0,
            station_name="Four Oaks",
        )
        assert action != "BRAKE"
        assert coord.last_brake_command is None or coord.last_brake_command.kind != "APPLY"

        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=60.0,
            next_limit_mph=55.0,
            distance_next_m=400.0,
            effective_limit=60.0,
            handle_notch=4,
            station_distance_m=550.0,
        )
        assert action == "HOLD"
        assert coord.last_target is not None
        assert coord.last_target.target_kind == "STATION"
        assert "unified" in coord.last_debug

    def test_unified_overspeed_brakes_to_limit_when_station_far(self):
        """58 mph con cartel 55 en zona y andén sin plan activo → APPLY, no sin_plan."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=58.0,
            next_limit_mph=55.0,
            distance_next_m=280.0,
            effective_limit=60.0,
            handle_notch=4,
            station_distance_m=530.0,
            station_name="Four Oaks",
        )
        assert coord.last_target is not None
        assert coord.last_target.target_kind == "SPEED_LIMIT"
        assert coord.last_brake_command is not None
        assert coord.last_brake_command.kind == "APPLY"
        assert coord.last_debug != "sin_plan_activo"

    def test_allows_release_when_stopped_at_platform(self):
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=1.0,
            next_limit_mph=55.0,
            distance_next_m=50.0,
            effective_limit=60.0,
            handle_notch=1,
            station_distance_m=80.0,
        )
        assert action == "RELEASE"


class TestCoordinatorEmergency:
    def test_station_critical_close(self):
        coord = _coord()
        action, eff = _eval(
            coord,
            speed_mph=45.0,
            next_limit_mph=55.0,
            distance_next_m=500.0,
            effective_limit=60.0,
            handle_notch=4,
            station_distance_m=30.0,
        )
        assert action in ("BRAKE", EMERGENCY)
        assert eff == 0.0
        assert coord.last_brake_command is not None
        assert "STATION" in coord.last_brake_command.reason

    def test_signal_emergency_red_aspect(self):
        coord = _coord()
        action, eff = _eval(
            coord,
            speed_mph=45.0,
            next_limit_mph=60.0,
            distance_next_m=500.0,
            effective_limit=75.0,
            handle_notch=4,
            signal_distance_m=30.0,
            signal_aspect="DANGER",
        )
        assert action in ("BRAKE", EMERGENCY)
        assert eff == 0.0
        assert coord.last_brake_command is not None
        assert "SIGNAL" in coord.last_brake_command.reason

    def test_no_emergency_for_speed_limit_only(self):
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=60.0,
            next_limit_mph=55.0,
            distance_next_m=150.0,
            effective_limit=70.0,
            handle_notch=4,
        )
        assert action == "HOLD"
        assert coord.last_brake_command is not None
        assert coord.last_brake_command.kind == "APPLY"
        assert "CRITICO" not in (coord.last_brake_command.reason or "")
        assert "EMERGENCIA" not in (coord.last_brake_command.reason or "")


class TestCoordinatorLimit:
    def test_limit_brake_apply_when_close(self):
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=60.0,
            next_limit_mph=55.0,
            distance_next_m=150.0,
            effective_limit=70.0,
            handle_notch=4,
        )
        assert action == "HOLD"
        assert coord.last_brake_command is not None
        assert coord.last_brake_command.kind == "APPLY"
        assert coord.last_target is not None
        assert coord.last_target.target_kind == "SPEED_LIMIT"

    def test_reset_clears_state(self):
        coord = _coord()
        _eval(coord, speed_mph=60.0, distance_next_m=150.0, handle_notch=4)
        assert coord.last_debug
        coord.reset()
        assert coord.last_debug == ""
        assert coord.last_brake_command is None
        assert coord.last_target is None


class TestCoordinatorInvestigateLog:
    def test_investigate_suffix_after_limit_brake(self):
        coord = _coord()
        _eval(
            coord,
            speed_mph=60.0,
            next_limit_mph=55.0,
            distance_next_m=150.0,
            effective_limit=70.0,
            handle_notch=4,
        )
        suffix = coord.investigate_suffix()
        assert "p1tgt=SPEED_LIMIT" in suffix
        assert "p1ds=" in suffix
        assert "p1d=" in suffix
        assert coord.last_brake_command is not None
        assert "p1cmd=APPLY" in suffix
