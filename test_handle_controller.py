"""
test_handle_controller.py — Tests unitarios para HandleController y SafetyWatchdog.

Verifica:
  - Target notch calculation por tipo de acción
  - Rate limiting
  - Supresión de COAST tras subida externa
  - SafetyWatchdog: overspeed y notch máximo
"""

import time
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from train_state import TrainState
from handle_controller import HandleController, SafetyWatchdog, _NOTCH_NEUTRAL, _MAX_NOTCH


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state(**overrides) -> TrainState:
    defaults: dict[str, Any] = dict(
        speed_mph=40.0, limit_mph=50.0, target_mph=0.0,
        handle_notch=4, acceleration_ms2=None, gradient_pct=0.0,
        rain_intensity=0.0, next_limit_mph=None, distance_next_m=None,
        brake_marker_m=None, speed_limits_ahead=None, supervision="csm",
        ack_required=False, stations=None, doors_open=False, doors_dmi=None,
        ocr_stop_dist_m=None, ocr_task=None, station_state=None,
        station_name=None, paused=False, timestamp=time.time(),
    )
    defaults.update(overrides)
    return TrainState(**defaults)


def _fresh() -> HandleController:
    c = HandleController()
    c._last_control = 0.0  # sin rate-limit
    return c


# ── Target notch ──────────────────────────────────────────────────────────────

class TestTargetNotch:
    def test_accelerate_increases(self):
        c = _fresh()
        assert c._target_notch("ACCELERATE", 4) == 5
        assert c._target_notch("ACCELERATE", 7) == 8
        assert c._target_notch("ACCELERATE", 8) == 8  # máximo

    def test_coast_no_below_neutral(self):
        c = _fresh()
        assert c._target_notch("COAST", 6) == 5
        assert c._target_notch("COAST", 5) == 4
        assert c._target_notch("COAST", 4) == 4  # ya en neutro: sin cambio
        assert c._target_notch("COAST", 3) == 3  # en zona freno: sin cambio

    def test_brake_releases_throttle_first(self):
        c = _fresh()
        # En zona de tracción: reduce tracción
        assert c._target_notch("BRAKE", 7) == 6
        assert c._target_notch("BRAKE", 5) == 4
        # En zona neutra / freno: aplica freno
        assert c._target_notch("BRAKE", 4) == 3
        assert c._target_notch("BRAKE", 2) == 1
        # Limite: no bajar de _BRAKE_MIN_HANDLE (1)
        assert c._target_notch("BRAKE", 1) == 1

    def test_hardbrake_jumps_to_neutral(self):
        c = _fresh()
        # Desde tracción: saltar a neutro
        assert c._target_notch("HARDBRAKE", 7) == 4
        assert c._target_notch("HARDBRAKE", 5) == 4
        # Desde neutro/freno: aplicar freno completo
        assert c._target_notch("HARDBRAKE", 4) == 3
        assert c._target_notch("HARDBRAKE", 1) == 0

    def test_fullstop_to_zero(self):
        c = _fresh()
        # Desde tracción: neutro primero
        assert c._target_notch("FULLSTOP", 6) == 4
        # Desde neutro/freno: freno máximo
        assert c._target_notch("FULLSTOP", 4) == 0
        assert c._target_notch("FULLSTOP", 2) == 0


# ── HOLD/PAUSED ───────────────────────────────────────────────────────────────

class TestHoldPaused:
    def test_hold_returns_false(self):
        c = _fresh()
        s = _state()
        assert c.execute("HOLD", s, None, None) is False

    def test_paused_returns_false(self):
        c = _fresh()
        s = _state()
        assert c.execute("PAUSED", s, None, None) is False


# ── Rate limiting ─────────────────────────────────────────────────────────────

class TestRateLimit:
    def test_rate_limit_blocks_second_call(self):
        c = HandleController()
        hwnd = MagicMock()

        with patch("handle_controller.send_key"):
            s = _state(handle_notch=4)
            # Primera llamada: pasa
            c.execute("ACCELERATE", s, None, hwnd)
            # Segunda llamada inmediata: bloqueada por rate-limit
            result = c.execute("ACCELERATE", s, None, hwnd)
        assert result is False

    def test_hardbrake_uses_shorter_interval(self):
        """HARDBRAKE tiene intervalo más corto que ACCELERATE."""
        from governor_constants import CONTROL_INTERVAL, CONTROL_INTERVAL_EMERG
        assert CONTROL_INTERVAL_EMERG < CONTROL_INTERVAL


# ── Teclado (mock hwnd) ───────────────────────────────────────────────────────

class TestKeyboard:
    def test_accelerate_sends_vk_a(self):
        from handle_controller import VK_A
        c = _fresh()
        s = _state(handle_notch=4)  # quiere subir a 5
        hwnd = MagicMock()

        with patch("handle_controller.send_key") as mock_send:
            result = c.execute("ACCELERATE", s, None, hwnd)
        assert result is True
        mock_send.assert_called_once_with(hwnd, VK_A)

    def test_coast_sends_vk_d(self):
        from handle_controller import VK_D
        c = _fresh()
        s = _state(handle_notch=6)  # quiere bajar a 5
        hwnd = MagicMock()

        with patch("handle_controller.send_key") as mock_send:
            result = c.execute("COAST", s, None, hwnd)
        assert result is True
        mock_send.assert_called_once_with(hwnd, VK_D)

    def test_no_hwnd_returns_false(self):
        c = _fresh()
        s = _state(handle_notch=4)
        result = c.execute("ACCELERATE", s, None, None)
        assert result is False

    def test_coast_when_already_neutral_no_send(self):
        """COAST en neutro no debe enviar nada (target == current)."""
        c = _fresh()
        s = _state(handle_notch=4)  # ya en neutro

        with patch("handle_controller.send_key") as mock_send:
            result = c.execute("COAST", s, None, 1)
        assert result is False
        mock_send.assert_not_called()


# ── Anti-oscilación: supresión de COAST ──────────────────────────────────────

class TestCoastSuppression:
    def test_coast_suppressed_after_external_boost(self):
        """Salto de +2 en notch (companion típico) activa la supresión."""
        c = _fresh()
        # Companion saltó de 4 a 6 (+2 = externo)
        c._last_seen_notch = 4
        c._last_control = time.time() - 2.0  # hace 2s (rate-limit OK)
        c._last_ext_up_t = time.time() - 0.5  # hace 0.5s (dentro de gracia)

        s = _state(handle_notch=6, ack_required=False)
        with patch("handle_controller.send_key") as mock_send:
            result = c.execute("COAST", s, None, 1)
        assert result is False
        mock_send.assert_not_called()

    def test_coast_not_suppressed_for_plus_one_jump(self):
        """Salto de +1 es nuestro propio comando — NO activa supresión."""
        c = _fresh()
        # Autopilot envió ACCELERATE, notch subió 4→5 (+1 = propio)
        c._last_seen_notch = 4
        # Simular: _last_ext_up_t queda del pasado (no fue detectado como externo)
        c._last_ext_up_t = 0.0

        s = _state(handle_notch=5, ack_required=False)
        with patch("handle_controller.send_key") as mock_send:
            result = c.execute("COAST", s, None, 1)
        assert result is True

    def test_coast_allowed_after_grace_period(self):
        c = _fresh()
        c._last_ext_up_t = time.time() - 2.0  # hace 2s (> 1.5s de gracia)

        s = _state(handle_notch=6, ack_required=False)
        with patch("handle_controller.send_key") as mock_send:
            result = c.execute("COAST", s, None, 1)
        assert result is True

    def test_coast_not_suppressed_during_ack(self):
        """Durante ACK, la supresión no aplica — hay que liberar tracción igualmente."""
        c = _fresh()
        c._last_ext_up_t = time.time() - 0.1  # boost muy reciente

        s = _state(handle_notch=6, ack_required=True)  # ACK activo
        with patch("handle_controller.send_key") as mock_send:
            result = c.execute("COAST", s, None, 1)
        assert result is True


# ── SafetyWatchdog ────────────────────────────────────────────────────────────

class TestSafetyWatchdog:
    def test_no_action_in_normal_conditions(self):
        w = SafetyWatchdog()
        s = _state(speed_mph=45.0, limit_mph=50.0)
        assert w.check(s) is None

    def test_no_action_for_small_excess(self):
        """Exceso < 5mph no activa watchdog."""
        w = SafetyWatchdog()
        s = _state(speed_mph=54.0, limit_mph=50.0)  # +4mph
        assert w.check(s) is None

    def test_hardbrake_after_persistent_overspeed(self):
        """Exceso >= 5mph durante >= 3s → HARDBRAKE."""
        w = SafetyWatchdog()
        # Exceso inmediato
        s = _state(speed_mph=57.0, limit_mph=50.0, acceleration_ms2=0.1)
        w.check(s)
        # Forzar que el timer de inicio sea hace 4s
        w._overspeed_since = time.time() - 4.0

        result = w.check(s)
        assert result == "HARDBRAKE"

    def test_overspeed_resets_when_speed_drops(self):
        w = SafetyWatchdog()
        s_over = _state(speed_mph=57.0, limit_mph=50.0)
        w.check(s_over)
        assert w._overspeed_since is not None

        s_ok = _state(speed_mph=52.0, limit_mph=50.0)  # < limit + 5
        w.check(s_ok)
        assert w._overspeed_since is None

    def test_no_action_for_notch_max_no_accel(self):
        """Notch máximo sin aceleración solo loguea, no devuelve acción."""
        w = SafetyWatchdog()
        s = _state(handle_notch=8, acceleration_ms2=0.02, speed_mph=0.0, limit_mph=50.0)
        result = w.check(s)
        assert result is None

    def test_no_action_when_limit_zero(self):
        """Con límite = 0, el watchdog no interviene."""
        w = SafetyWatchdog()
        s = _state(speed_mph=60.0, limit_mph=0.0)
        assert w.check(s) is None
