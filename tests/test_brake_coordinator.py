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

    def test_no_release_when_parked_at_scenario_start(self):
        """Arranque: freno aplicado, spd≈0 y cartel lejos — no tocar el handle."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=0.0,
            next_limit_mph=45.0,
            distance_next_m=271.0,
            effective_limit=20.0,
            gradient_pct=0.2,
            handle_notch=1,
            station_distance_m=11204.0,
            station_name="Four Oaks",
        )
        assert action != "RELEASE"
        assert coord.last_brake_command is None or coord.last_brake_command.kind != "RELEASE"

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
        """54 mph, 550 m al andén: aún fuera del horizonte de servicio → soltar el 55."""
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

    def test_release_after_limit_tap_before_station_horizon(self):
        """Tras B1 al 55, andén aún fuera del horizonte 80%: soltar a neutro."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=55.2,
            next_limit_mph=55.0,
            distance_next_m=429.0,
            effective_limit=60.0,
            handle_notch=3,
            station_distance_m=684.0,
            station_name="Four Oaks",
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

    def test_no_unified_force_release_while_0_9_over_posted(self):
        """Sesión 17:25:05 — 55.9 vs cartel 55, B1 puesto, andén aún lejos: no soltar."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=55.9,
            next_limit_mph=55.0,
            distance_next_m=435.0,
            effective_limit=60.0,
            handle_notch=3,
            station_distance_m=699.0,
            station_name="Four Oaks",
        )
        assert action != "RELEASE"
        if coord.last_brake_command is not None:
            assert coord.last_brake_command.kind != "RELEASE"

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

    def test_station_wins_over_downhill_containment_in_unified_window(self):
        """Bajada -1%: en ventana de parada la estación gana sobre contención B1."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=30.0,
            next_limit_mph=55.0,
            distance_next_m=80.0,
            effective_limit=60.0,
            gradient_pct=-1.0,
            handle_notch=2,
            station_distance_m=200.0,
            station_name="Four Oaks",
        )
        assert coord.last_target is not None
        assert coord.last_target.target_kind == "STATION"
        assert coord.last_brake_command is not None
        assert coord.last_brake_command.kind == "APPLY"
        assert "Contención bajada" not in (coord.last_debug or "")

    def test_downhill_containment_only_before_station_window(self):
        """Repunte a 55.4 en bajada lejos del andén: B1 cartel, sin plan estación aún."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=55.4,
            next_limit_mph=55.0,
            distance_next_m=80.0,
            effective_limit=60.0,
            gradient_pct=-1.0,
            handle_notch=4,
            station_distance_m=600.0,
            station_name="Four Oaks",
        )
        assert coord.last_target is not None
        assert coord.last_target.target_kind == "SPEED_LIMIT"
        assert coord.last_target.phase == "B1"
        assert "Contención bajada" in (coord.last_target.detail or "")

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
        assert action in ("HOLD", "BRAKE")
        assert coord.last_target is not None
        assert coord.last_target.target_kind == "SPEED_LIMIT"
        assert "unified" in coord.last_debug

    def test_unified_overspeed_brakes_to_station_when_gap_short(self):
        """58 mph, cartel 280 m, andén 530 m: el 55 marca el APPLY; no B1 de andén."""
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

    def test_unified_overspeed_60_uses_limit_timing(self):
        """60 mph, cartel 400 m, andén 550 m: APPLY del 55, no B1 a ~800 m."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=60.0,
            next_limit_mph=55.0,
            distance_next_m=400.0,
            effective_limit=60.0,
            handle_notch=4,
            station_distance_m=550.0,
            station_name="Four Oaks",
        )
        assert coord.last_target is not None
        assert coord.last_target.target_kind == "SPEED_LIMIT"
        assert coord.last_brake_command is not None
        assert coord.last_brake_command.kind == "APPLY"

    def test_no_release_when_stopped_without_station_plan(self):
        """Parado cerca del andén sin plan activo (spd≈0): no soltar por cartel."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=1.0,
            next_limit_mph=55.0,
            distance_next_m=50.0,
            effective_limit=60.0,
            handle_notch=1,
            station_distance_m=50.0,
        )
        assert action != "RELEASE"


class TestCoordinatorStationReleaseBlock:
    def test_no_release_oscillation_during_station_approach(self):
        """B1 @55: no soltar mientras el cartel sigue por delante."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=54.0,
            next_limit_mph=55.0,
            distance_next_m=120.0,
            effective_limit=60.0,
            gradient_pct=-0.5,
            handle_notch=3,
            station_distance_m=400.0,
            station_name="Sutton Coldfield",
        )
        assert action != "RELEASE"

    def test_release_when_unified_overbraked_after_sign(self):
        """Tras el 55, B1 con holgura al andén: soltar (evita parar 130 m corto)."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=26.0,
            next_limit_mph=55.0,
            distance_next_m=5.0,
            effective_limit=55.0,
            handle_notch=3,
            station_distance_m=272.0,
            station_name="Four Oaks",
        )
        assert action == "RELEASE"

    def test_release_allowed_when_station_far(self):
        """55 mph, andén fuera de cluster: soltar el cartel (no unificado)."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=55.0,
            next_limit_mph=55.0,
            distance_next_m=700.0,
            effective_limit=60.0,
            gradient_pct=0.0,
            handle_notch=3,
            station_distance_m=1500.0,
            station_name="Four Oaks",
        )
        assert action == "RELEASE"


class TestCoordinatorLimitBeforeStation:
    def test_inverted_hud_does_not_station_stop_before_55(self):
        """Log 01:24:07: Four Oaks @442 m, 55 @927 m — 60→55, no STATION a 0."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=59.0,
            next_limit_mph=55.0,
            distance_next_m=927.0,
            effective_limit=60.0,
            gradient_pct=-0.6,
            handle_notch=4,
            station_distance_m=442.0,
            station_name="Four Oaks",
        )
        assert coord.last_target is not None
        assert coord.last_target.target_kind == "SPEED_LIMIT"
        assert coord.last_target.target_speed_mph == 55.0
        if coord.last_brake_command is not None:
            assert "STATION" not in (coord.last_brake_command.reason or "")
            assert "EMERGENCIA" not in (coord.last_brake_command.reason or "")

    def test_inverted_hud_no_station_emergency_before_55(self):
        """Log 02:02:29: HUD 234 m, 55 @700 m, 59 mph — no P1-EMERGENCIA-STATION."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=58.7,
            next_limit_mph=55.0,
            distance_next_m=709.0,
            effective_limit=60.0,
            gradient_pct=-1.0,
            handle_notch=4,
            station_distance_m=234.0,
            station_name="Four Oaks",
        )
        assert action != "EMERGENCY"
        if coord.last_brake_command is not None:
            assert "EMERGENCIA-STATION" not in (coord.last_brake_command.reason or "")
            assert "CRITICO-STATION" not in (coord.last_brake_command.reason or "")
        if coord.last_target is not None:
            assert coord.last_target.target_kind == "SPEED_LIMIT"

    def test_inverted_hud_at_55_does_not_hold_station_b3(self):
        """HUD andén más cerca que el 55: a ~55 mph no unificar a parada 0."""
        coord = _coord()
        _eval(
            coord,
            speed_mph=55.7,
            next_limit_mph=55.0,
            distance_next_m=876.0,
            effective_limit=60.0,
            gradient_pct=-0.6,
            handle_notch=1,
            station_distance_m=361.0,
            station_name="Four Oaks",
        )
        if coord.last_target is not None:
            assert coord.last_target.target_kind != "STATION"

    def test_sutton_next_60_does_not_block_station(self):
        """Log 02:18:04: 35 vigente, 60 tras el andén — frenar Sutton, no esperar."""
        coord = _coord()
        _eval(
            coord,
            speed_mph=34.8,
            next_limit_mph=60.0,
            distance_next_m=533.0,
            effective_limit=35.0,
            gradient_pct=-1.0,
            handle_notch=4,
            station_distance_m=464.0,
            station_name="Sutton Coldfield",
        )
        assert coord.last_target is not None
        assert coord.last_target.target_kind == "STATION"

    def test_downhill_holds_posted_limit_while_next_is_far(self):
        """Log 02:17:09: 48 mph en 45, 35 a 900 m — sujetar 45, no solo aware del 35."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=46.2,
            next_limit_mph=35.0,
            distance_next_m=1500.0,
            effective_limit=45.0,
            gradient_pct=-1.0,
            handle_notch=4,
        )
        assert coord.last_target is not None
        assert coord.last_target.target_kind == "SPEED_LIMIT"
        assert coord.last_target.apply_now
        assert coord.last_target.target_speed_mph == 45.0
        assert coord.last_brake_command is not None
        assert coord.last_brake_command.kind == "APPLY"


class TestCoordinatorEmergency:
    def test_station_critical_close(self):
        coord = _coord()
        action, eff = _eval(
            coord,
            speed_mph=45.0,
            next_limit_mph=55.0,
            distance_next_m=8.0,
            effective_limit=55.0,
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

    def test_brakes_on_current_limit_when_last_sign_passed(self):
        """Último cartel 60→45: sin next_limit en cola pero spd>45 — debe frenar."""
        coord = _coord()
        action, _ = _eval(
            coord,
            speed_mph=58.0,
            next_limit_mph=None,
            distance_next_m=None,
            effective_limit=45.0,
            handle_notch=4,
        )
        assert action == "HOLD"
        assert coord.last_target is not None
        assert coord.last_target.target_kind == "SPEED_LIMIT"
        assert coord.last_brake_command is not None
        assert coord.last_brake_command.kind == "APPLY"

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
