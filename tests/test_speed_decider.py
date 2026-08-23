"""
test_speed_decider.py — Tests unitarios para SpeedDecider.

Verifica:
  - P2: crucero, overspeed, HARDBRAKE
  - P3: proyección de velocidad, anti-oscilación
  - ACK: supervisión ATP
  - Pausa
  - Integración básica con TrainState
"""

import time
from typing import Any, Optional

import pytest

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
        assert d.decide(s) == "PAUSED"

    def test_not_paused_does_not_return_paused(self):
        d = _decider()
        s = _state(paused=False, speed_mph=40.0, limit_mph=50.0)
        assert d.decide(s) != "PAUSED"


# ── ACK ───────────────────────────────────────────────────────────────────────

class TestAck:
    def test_ack_with_throttle_returns_coast(self):
        d = _decider()
        s = _state(ack_required=True, handle_notch=6, speed_mph=50.0, limit_mph=50.0)
        assert d.decide(s) == "COAST"

    def test_ack_over_limit_returns_hold(self):
        """Durante ACK cedemos al ATP — no enviamos BRAKE, solo HOLD."""
        d = _decider()
        s = _state(ack_required=True, handle_notch=4, speed_mph=55.0, limit_mph=50.0)
        assert d.decide(s) == "HOLD"

    def test_ack_below_limit_returns_hold(self):
        d = _decider()
        s = _state(ack_required=True, handle_notch=4, speed_mph=45.0, limit_mph=50.0)
        assert d.decide(s) == "HOLD"

    def test_ack_no_accelerate_from_brake_zone(self):
        """Durante ACK nunca enviamos ACCELERATE — cede el ATP."""
        d = _decider()
        s = _state(ack_required=True, handle_notch=1, speed_mph=15.0, limit_mph=50.0)
        assert d.decide(s) == "HOLD"

    def test_ack_sets_effective_limit(self):
        d = _decider()
        s = _state(ack_required=True, limit_mph=60.0, speed_mph=50.0, handle_notch=4)
        d.decide(s)
        assert d.effective_limit == 60.0


# ── P2: Crucero ───────────────────────────────────────────────────────────────

class TestP2Cruise:
    def test_below_limit_with_throttle_no_brake(self):
        """Por debajo del límite con tracción: debería acelerarse o mantener."""
        d = _decider()
        s = _state(speed_mph=45.0, limit_mph=50.0, handle_notch=5, acceleration_ms2=0.5)
        action = d.decide(s)
        assert action not in ("BRAKE", "HARDBRAKE", "FULLSTOP")

    def test_over_limit_with_residual_acceleration_coasts(self):
        """Por encima del límite con tracción activa y aceleración positiva: COAST."""
        d = _decider()
        # Tren acelerando activamente (handle=6) mientras supera el límite
        s = _state(speed_mph=52.0, limit_mph=50.0, handle_notch=6, acceleration_ms2=0.2)
        action = d.decide(s)
        assert action == "COAST"

    def test_over_limit_with_throttle_coast(self):
        """Por encima del límite con tracción activa: COAST primero."""
        d = _decider()
        s = _state(speed_mph=52.0, limit_mph=50.0, handle_notch=6, acceleration_ms2=0.0)
        action = d.decide(s)
        assert action == "COAST"

    def test_critical_overspeed_hardbrake(self):
        """Exceso crítico sobre límite: HARDBRAKE."""
        d = _decider()
        s = _state(speed_mph=56.0, limit_mph=50.0, handle_notch=4,
                   acceleration_ms2=0.0, station_state=None)
        action = d.decide(s)
        assert action == "HARDBRAKE"


# ── Solo frenado (sin tracción automática) ─────────────────────────────────────

class TestBrakeOnly:
    def test_below_limit_holds(self):
        """Sin tracción automática: no acelera aunque falte velocidad."""
        d = _decider()
        s = _state(speed_mph=25.0, limit_mph=50.0, handle_notch=4,
                   acceleration_ms2=None)
        assert d.decide(s) == "HOLD"

    def test_overspeed_still_brakes(self):
        d = _decider()
        s = _state(speed_mph=56.0, limit_mph=50.0, handle_notch=7,
                   acceleration_ms2=0.1, station_state=None)
        assert d.decide(s) in ("COAST", "BRAKE", "HARDBRAKE")

    def test_brake_residual_holds(self):
        """Freno residual: conductor libera manualmente."""
        d = _decider()
        s = _state(speed_mph=40.0, limit_mph=50.0, handle_notch=2,
                   acceleration_ms2=0.0, station_state=None)
        assert d.decide(s) == "HOLD"


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
