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

from train_state import TrainState, build_train_state
from speed_decider import SpeedDecider


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state(**overrides) -> TrainState:
    defaults: dict[str, Any] = dict(
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


# ── P3: Rastreo de aceleración objetivo ──────────────────────────────────────

class TestP3AccelerationTracking:
    def test_far_below_limit_no_accel_data_accelerates(self):
        """Sin acelerómetro y lejos del límite: tabla abierta → ACCELERATE."""
        d = _decider()
        s = _state(speed_mph=25.0, limit_mph=50.0, handle_notch=4,
                   acceleration_ms2=None)
        action = d.decide(s)
        assert action == "ACCELERATE"

    def test_accel_below_target_accelerates(self):
        """Aceleración medida < a_target → añadir muesca (ACCELERATE)."""
        d = _decider()
        # error=10 mph, a_target = min(10*0.44704/8, TARGET_ACCEL) ≈ 0.301 m/s²
        # a=0.1 < 0.301 - 0.05 = 0.251 → ACCELERATE
        s = _state(speed_mph=40.0, limit_mph=50.0, handle_notch=5,
                   acceleration_ms2=0.1)
        action = d.decide(s)
        assert action == "ACCELERATE"

    def test_accel_matches_target_hold(self):
        """Aceleración medida ≈ a_target (dentro de tolerancia) → HOLD."""
        d = _decider()
        # error=10 mph → a_target = min(10*0.44704/8, TARGET_ACCEL=0.301) = 0.301 m/s²
        # a=0.30 → |0.30 - 0.301| = 0.001 < P3_ACCEL_TOL=0.05 → HOLD
        s = _state(speed_mph=40.0, limit_mph=50.0, handle_notch=6,
                   acceleration_ms2=0.30)
        action = d.decide(s)
        assert action == "HOLD"

    def test_accel_above_target_coasts(self):
        """Aceleración medida >> a_target → bajar muesca (COAST)."""
        d = _decider()
        # error=5 mph → a_target = min(5*0.44704/8, 0.301) = 0.279 m/s²
        # a=0.6 > 0.279 + 0.05 = 0.329 → COAST
        s = _state(speed_mph=45.0, limit_mph=50.0, handle_notch=7,
                   acceleration_ms2=0.6)
        action = d.decide(s)
        assert action == "COAST"

    def test_near_limit_uses_low_notch(self):
        """Cerca del límite a_target es pequeño: aceleración media → COAST o HOLD (no ACCELERATE)."""
        d = _decider()
        # error=2 mph → a_target = min(2*0.44704/8, 0.301) = 0.112 m/s²
        # a=0.3 > 0.112 + 0.05 = 0.162 → COAST
        s = _state(speed_mph=48.0, limit_mph=50.0, handle_notch=7,
                   acceleration_ms2=0.3)
        action = d.decide(s)
        assert action in ("COAST", "HOLD")

    def test_anti_oscillation_hold(self):
        """Anti-oscilación: cambio de dirección se retrasa P3_DEADBAND_CYCLES ciclos."""
        from governor_constants import P3_DEADBAND_CYCLES

        d = _decider()
        # Primer ciclo: a baja → sube notch (direction="up")
        # error=10 mph, a=0.01 < a_target-tol → ACCELERATE, last_dir="up"
        s_acc = _state(speed_mph=40.0, limit_mph=50.0, handle_notch=5,
                       acceleration_ms2=0.01)
        d.decide(s_acc)

        # Siguiente ciclo: a muy alta → quiere bajar notch (direction="down")
        # error=10, a=0.8 > a_target+0.05 → COAST. Cambio up→down: deadband → HOLD
        s_coast = _state(speed_mph=40.0, limit_mph=50.0, handle_notch=5,
                         acceleration_ms2=0.8)
        for i in range(P3_DEADBAND_CYCLES):
            action = d.decide(s_coast)
            assert action == "HOLD", f"Ciclo {i}: esperaba HOLD, recibí {action}"


class TestPredictiveNotchSelection:
    """Selección predictiva de la muesca mínima suficiente (datos por muesca)."""

    def _decider_with_data(self) -> SpeedDecider:
        from online_learner import _speed_band_index, MIN_SAMPLES
        d = _decider()
        lr = d._physics.learner
        band = _speed_band_index(15.0)
        # Tracción-1..4 (handle 5..8) aceleración aprendida (plano), n suficiente
        for notch, a in ((5, 0.06), (6, 0.18), (7, 0.45), (8, 0.55)):
            lr._ema_bands[band][notch] = a
            lr._n_bands[band][notch]   = MIN_SAMPLES
        return d

    def test_picks_minimum_sufficient_notch(self):
        """a_target=0.15 → la muesca mínima suficiente es Tracción-2 (handle6, t=2)."""
        d = self._decider_with_data()
        assert d._select_notch_predictive(0.15, 15.0, 0.0) == 2

    def test_low_target_picks_lowest(self):
        """a_target pequeño (por encima del umbral de soltar) → Tracción-1 (t=1)."""
        d = self._decider_with_data()
        # 0.10 > tol(0.05) → no suelta; Tracción-1 (0.06) ya alcanza 0.10-tol
        assert d._select_notch_predictive(0.10, 15.0, 0.0) == 1

    def test_high_target_picks_max(self):
        """a_target inalcanzable → tracción máxima (t=4)."""
        d = self._decider_with_data()
        assert d._select_notch_predictive(2.0, 15.0, 0.0) == 4

    def test_zero_target_releases_to_neutral(self):
        """a_target ~0 → soltar a neutro (t=0)."""
        d = self._decider_with_data()
        assert d._select_notch_predictive(0.0, 15.0, 0.0) == 0

    def test_no_data_returns_none(self):
        """Sin datos aprendidos → None (P3 usa fallback reactivo)."""
        d = _decider()
        assert d._select_notch_predictive(0.2, 15.0, 0.0) is None

    def test_uphill_needs_higher_notch(self):
        """En subida la misma a_target exige una muesca mayor (gravedad)."""
        d = self._decider_with_data()
        flat = d._select_notch_predictive(0.15, 15.0, 0.0)
        up   = d._select_notch_predictive(0.15, 15.0, 2.0)
        assert flat is not None and up is not None
        assert up >= flat


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
