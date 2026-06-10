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
from typing import Optional

import pytest

from train_state import TrainState, build_train_state
from speed_decider import SpeedDecider


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state(**overrides) -> TrainState:
    defaults = dict(
        speed_mph=40.0, limit_mph=50.0, target_mph=0.0,
        handle_notch=4, acceleration_ms2=0.3, gradient_pct=0.0,
        rain_intensity=0.0, next_limit_mph=None, distance_next_m=None,
        brake_marker_m=None, speed_limits_ahead=None, supervision="csm",
        ack_required=False, stations=None, doors_open=False, doors_dmi=None,
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


# ── P3: Proyección de velocidad ───────────────────────────────────────────────

class TestP3VelocityProjection:
    def test_far_below_limit_accelerates(self):
        """Muy por debajo del límite sin acelerómetro: debe querer acelerar."""
        d = _decider()
        # handle en neutro, 15 mph por debajo del límite, sin aceleración API
        s = _state(speed_mph=25.0, limit_mph=50.0, handle_notch=4,
                   acceleration_ms2=None)
        action = d.decide(s)
        assert action == "ACCELERATE"

    def test_projection_at_limit_hold(self):
        """Proyección de velocidad justo en el límite: HOLD."""
        d = _decider()
        # speed=48, limit=50, a=0.11 m/s², lookahead=8s
        # v_proj = 48 + (0.11 * 8) / 0.44704 ≈ 48 + 1.97 ≈ 49.97
        # proj_err = 50 - 49.97 = 0.03 < P3_SPEED_TOL_MPH(2.0) → HOLD
        s = _state(speed_mph=48.0, limit_mph=50.0, handle_notch=4,
                   acceleration_ms2=0.11)
        action = d.decide(s)
        assert action == "HOLD"

    def test_projection_too_fast_coast(self):
        """Proyección supera límite: debería COAST o bajar notch."""
        d = _decider()
        # speed=48, a=0.5 m/s², v_proj = 48 + (0.5*8)/0.44704 ≈ 57
        # proj_err = 50 - 57 = -7 < -P3_SPEED_TOL_MPH → target_t = max(0-1, 0) = 0
        # throttle_notch=0 y target_t=0 → no hay cambio → HOLD
        # Si throttle_notch=1, target_t=0 → COAST
        s = _state(speed_mph=48.0, limit_mph=50.0, handle_notch=5,
                   acceleration_ms2=0.5)
        action = d.decide(s)
        assert action in ("COAST", "HOLD")

    def test_anti_oscillation_hold(self):
        """Anti-oscilación: cambio de dirección se retrasa P3_DEADBAND_CYCLES ciclos."""
        from governor_constants import P3_DEADBAND_CYCLES

        d = _decider()
        # Primer ciclo: proyección baja → sube notch (direction="up")
        # speed=40, limit=50, a≈0.01: v_proj ≈ 40.18, proj_err=9.82 > 2 → ACCELERATE
        s_acc = _state(speed_mph=40.0, limit_mph=50.0, handle_notch=4,
                       acceleration_ms2=0.01)
        d.decide(s_acc)  # establece last_direction = "up"

        # Siguiente ciclo: proyección muy alta → quiere bajar notch (direction="down")
        # speed=40, limit=50, handle=5 (throttle_notch=1), a=0.8:
        # v_proj = 40 + (0.8*8)/0.44704 ≈ 54.3, proj_err = -4.3 → target_t=0 < th_n=1
        # Cambio de dirección up→down: debe activar deadband → HOLD
        s_coast = _state(speed_mph=40.0, limit_mph=50.0, handle_notch=5,
                         acceleration_ms2=0.8)
        for i in range(P3_DEADBAND_CYCLES):
            action = d.decide(s_coast)
            assert action == "HOLD", f"Ciclo {i}: esperaba HOLD, recibí {action}"


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
