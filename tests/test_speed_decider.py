"""
test_speed_decider.py — Tests unitarios para SpeedDecider.

Verifica:
  - HOLD por defecto sin plan P1
  - Pausa
  - Integración básica con TrainState y P1 v2
"""

import time
from typing import Any, Optional

import pytest

from tsw6.autopilot.control_actions import (
    BRAKE, BRAKE_FAST, COAST, EMERGENCY, HOLD, PAUSED, RELEASE,
)
from tsw6.autopilot.train_state import TrainState, build_train_state
from tsw6.autopilot.speed_decider import SpeedDecider


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state(**overrides) -> TrainState:
    defaults: dict[str, Any] = dict(
        speed_mph=40.0, limit_mph=50.0, target_mph=0.0,
        handle_notch=4, acceleration_ms2=0.3, gradient_pct=0.0,
        rain_intensity=0.0, next_limit_mph=None, distance_next_m=None,
        brake_marker_m=None, speed_limits_ahead=None, supervision="csm",
        ack_required=False, stations=None, doors_open=False, doors_telem=None,
        doors_dmi=None,
        ocr_stop_dist_m=None, ocr_task=None, station_state=None,
        station_name=None, paused=False, timestamp=time.time(),
    )
    defaults.update(overrides)
    return TrainState(**defaults)


def _decider(**kwargs) -> SpeedDecider:
    return SpeedDecider(**kwargs)


# ── Pausa ─────────────────────────────────────────────────────────────────────

class TestPaused:
    def test_paused_returns_paused(self):
        d = _decider()
        s = _state(paused=True)
        assert d.decide(s) == PAUSED

    def test_not_paused_does_not_return_paused(self):
        d = _decider()
        s = _state(paused=False, speed_mph=40.0, limit_mph=50.0)
        assert d.decide(s) != PAUSED



# ── Sin plan P1 ───────────────────────────────────────────────────────────────

class TestNoP1Plan:
    def test_below_limit_holds(self):
        d = _decider()
        s = _state(speed_mph=45.0, limit_mph=50.0, handle_notch=5, acceleration_ms2=0.5)
        assert d.decide(s) == HOLD

    def test_overspeed_with_throttle_coasts_first(self):
        """P1 activo sin cartel adelante: soltar tracción antes de frenar."""
        d = _decider()
        s = _state(speed_mph=52.0, limit_mph=50.0, handle_notch=6, acceleration_ms2=0.2)
        assert d.decide(s) == COAST

    def test_critical_overspeed_brakes_on_current_limit(self):
        d = _decider()
        s = _state(speed_mph=56.0, limit_mph=50.0, handle_notch=4,
                   acceleration_ms2=0.0, station_state=None)
        action = d.decide(s)
        assert action == HOLD
        assert d.brake_command is not None
        assert d.brake_command.kind == "APPLY"


# ── Solo frenado (sin tracción automática) ─────────────────────────────────────

class TestBrakeOnly:
    def test_below_limit_holds(self):
        """Sin tracción automática: no acelera aunque falte velocidad."""
        d = _decider()
        s = _state(speed_mph=25.0, limit_mph=50.0, handle_notch=4,
                   acceleration_ms2=None)
        assert d.decide(s) == HOLD

    def test_overspeed_engages_p1_on_current_limit(self):
        d = _decider()
        s = _state(speed_mph=56.0, limit_mph=50.0, handle_notch=7,
                   acceleration_ms2=0.1, station_state=None)
        assert d.decide(s) == COAST

    def test_brake_residual_holds(self):
        """Freno residual: conductor libera manualmente."""
        d = _decider()
        s = _state(speed_mph=40.0, limit_mph=50.0, handle_notch=2,
                   acceleration_ms2=0.0, station_state=None)
        assert d.decide(s) == HOLD


class TestBrakeCommand:
    def test_brake_command_only_from_p1(self):
        from tsw6.braking.v2.command import BrakeCommand

        d = _decider()
        s = _state(speed_mph=56.0, limit_mph=50.0, handle_notch=4)
        assert d.brake_command_for(BRAKE_FAST, s) is None
        p1_cmd = BrakeCommand(kind="APPLY", target_notch=2, phase="B2", reason="P1")
        d._braking.last_brake_command = p1_cmd
        assert d.brake_command_for(BRAKE_FAST, s) is p1_cmd


# ── last_action tracking ──────────────────────────────────────────────────────

class TestLastAction:
    def test_last_action_updated(self):
        d = _decider()
        s = _state(speed_mph=56.0, limit_mph=50.0, handle_notch=4, station_state=None)
        action = d.decide(s)
        assert d.last_action == action

    def test_paused_sets_last_action(self):
        d = _decider()
        s = _state(paused=True)
        d.decide(s)
        assert d.last_action == "PAUSED"


# ── effective_limit ───────────────────────────────────────────────────────────

class TestEffectiveLimit:
    def test_no_target_follows_limit(self):
        d = _decider()
        s = _state(speed_mph=40.0, limit_mph=60.0, target_mph=0.0,
                   handle_notch=5, acceleration_ms2=0.1)
        d.decide(s)
        assert d.effective_limit == 60.0

    def test_target_below_limit(self):
        d = _decider()
        s = _state(speed_mph=40.0, limit_mph=60.0, target_mph=45.0,
                   handle_notch=4, acceleration_ms2=0.1)
        d.decide(s)
        assert d.effective_limit == 45.0


# ── Propiedades de compatibilidad con dashboard ───────────────────────────────

class TestDashboardProperties:
    def test_throttle_notch_from_last_state(self):
        d = _decider()
        s = _state(handle_notch=7)  # throttle_notch = 3
        d.decide(s)
        assert d.throttle_notch == 3

    def test_brake_notch_from_last_state(self):
        d = _decider()
        s = _state(handle_notch=2)  # brake_notch = 2
        d.decide(s)
        assert d.brake_notch == 2

    def test_current_notch_from_last_state(self):
        d = _decider()
        s = _state(handle_notch=6)
        d.decide(s)
        assert d.current_notch == 6

    def test_braking_distance_delegate(self):
        d = _decider()
        bd = d.braking_distance(50.0, 30.0)
        assert bd > 0

    def test_station_state_initial_none(self):
        d = _decider()
        assert d.station_state is None

    def test_target_stop_min_m_property(self):
        d = _decider()
        d.target_stop_min_m = 1500.0
        assert d.target_stop_min_m == 1500.0
        assert d._fsm.target_stop_min_m == 1500.0


class TestP1V2Integration:
    def test_decider_uses_brake_coordinator_v2(self):
        from tsw6.braking.v2.coordinator import BrakeCoordinatorV2

        d = _decider()
        assert isinstance(d._braking, BrakeCoordinatorV2)

    def test_p1_limit_produces_brake_command(self):
        d = _decider()
        s = _state(
            speed_mph=60.0,
            limit_mph=70.0,
            next_limit_mph=55.0,
            distance_next_m=150.0,
            speed_limits_ahead=({"limit_mph": 55.0, "distance_m": 150.0},),
        )
        action = d.decide(s)
        assert action == "HOLD"
        assert d.brake_command is not None
        assert d.brake_command.kind == "APPLY"
        assert "v2" in d.p1_debug

    def test_p1_reset_when_fsm_approaching_slow(self):
        from tsw6.braking.v2.coordinator import BrakeCoordinatorV2

        d = _decider()
        d._braking.last_debug = "prev"
        s = _state(
            speed_mph=5.0,
            station_state="APPROACHING",
            next_limit_mph=25.0,
            distance_next_m=500.0,
        )
        d.decide(s)
        assert isinstance(d._braking, BrakeCoordinatorV2)
        assert d._braking.last_debug == ""

    def test_p1_stays_active_approaching_with_brake_handle(self):
        """C.2: B1 a 10 mph no hace P1 reset (log Four Oaks)."""
        d = _decider()
        s = _state(
            speed_mph=10.0,
            handle_notch=3,
            station_state="APPROACHING",
            station_name="Four Oaks, andén 2",
            next_stop_name="Sutton Coldfield, andén 2",
            next_stop_distance_m=2261.0,
            next_limit_mph=55.0,
            distance_next_m=2495.8,
        )
        d.decide(s)
        assert d.p1_active is True

    def test_p1_station_distance_uses_fsm_not_jumped_next_stop(self):
        d = _decider()
        d._fsm.state = "APPROACHING"
        d._fsm.name = "Four Oaks, andén 2"
        s = _state(
            station_state="APPROACHING",
            station_name="Four Oaks, andén 2",
            next_stop_name="Sutton Coldfield, andén 2",
            next_stop_distance_m=2261.0,
            stations=(
                {"name": "Four Oaks, andén 2", "distance_m": 110.0},
                {"name": "Sutton Coldfield, andén 2", "distance_m": 2261.0},
            ),
        )
        stns = list(s.stations) if s.stations else []
        assert d._p1_station_target(s) == "Four Oaks, andén 2"
        assert d._p1_station_distance(s, stns) == 110.0

    def test_p1_hold_when_stopped_at_platform_until_doors(self):
        """Parado en andén: HOLD con B1; RELEASE al cerrar puertas (Lua)."""
        d = _decider()
        d._p1_was_active = True
        s = _state(
            speed_mph=0.0,
            handle_notch=3,
            station_state="APPROACHING",
            station_name="Four Oaks, andén 2",
            stations=(
                {"name": "Four Oaks, andén 2", "distance_m": 101.0,
                 "scheduled": True, "platform_length_m": 100.0},
            ),
        )
        d._fsm.state = "APPROACHING"
        d._fsm.name = "Four Oaks, andén 2"
        d._fsm._we_stopped = True
        action = d.decide(s)
        assert d._fsm.state == "STOPPED"
        assert action == HOLD

    def test_p1_idle_when_stopped_neutral(self):
        """STOPPED con palanca en neutro: no RELEASE (no pelear tracción)."""
        d = _decider()
        d._fsm.state = "STOPPED"
        d._fsm.name = "Four Oaks, andén 2"
        d._fsm._stopped_at = time.time()
        s = _state(
            speed_mph=0.0,
            handle_notch=4,
            station_state="STOPPED",
            station_name="Four Oaks, andén 2",
            stations=(
                {"name": "Sutton Coldfield, andén 2", "distance_m": 2191.0,
                 "scheduled": True},
            ),
        )
        action = d.decide(s)
        assert action == HOLD
        assert d.brake_command is None

    def test_release_on_lua_door_close_while_braked(self):
        """Cierre PassengerDoor: DEPARTING y RELEASE (no dwell a tiempo)."""
        d = _decider()
        d._fsm.state = "STOPPED"
        d._fsm.name = "Four Oaks, andén 2"
        d._fsm._stopped_at = time.time()
        d._fsm._we_stopped = True
        stations = (
            {"name": "Four Oaks, andén 2", "distance_m": 8.0,
             "scheduled": True, "platform_length_m": 100.0},
            {"name": "Sutton Coldfield, andén 2", "distance_m": 2191.0,
             "scheduled": True, "platform_length_m": 100.0},
        )
        open_act = d.decide(_state(
            speed_mph=0.0, handle_notch=0, station_state="STOPPED",
            station_name="Four Oaks, andén 2", stations=stations,
            doors_telem=True, doors_dmi=None,
        ))
        assert d._fsm.state == "STOPPED"
        assert open_act == HOLD
        action = d.decide(_state(
            speed_mph=0.0, handle_notch=0, station_state="STOPPED",
            station_name="Four Oaks, andén 2", stations=stations,
            doors_telem=False, doors_dmi=None,
        ))
        assert d._fsm.state == "DEPARTING"
        assert action == RELEASE
        nxt = d._fsm.select_next_stop(list(stations))
        assert nxt is not None
        assert "Sutton" in nxt["name"]

    def test_p1_passes_station_eta_to_coordinator(self):
        from unittest.mock import patch

        d = _decider()
        captured: dict = {}

        def _capture_evaluate(**kwargs):
            captured.update(kwargs)
            return None, 60.0

        s = _state(
            speed_mph=44.7,
            limit_mph=75.0,
            next_stop_distance_m=900.0,
            next_stop_name="Four Oaks",
            next_stop_arrival="14:38",
            stations=({"name": "Four Oaks", "distance_m": 900.0},),
        )
        with patch.object(d._braking, "evaluate", side_effect=_capture_evaluate):
            d.decide(s)
        assert captured.get("station_eta") == "14:38"
        assert captured.get("station_distance_m") == 900.0
