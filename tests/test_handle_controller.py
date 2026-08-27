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

from tsw6.autopilot.control_actions import (
    BRAKE, BRAKE_FAST, COAST, EMERGENCY, HOLD, PAUSED,
)
from tsw6.autopilot.train_state import TrainState
from tsw6.autopilot.handle_controller import HandleController, SafetyWatchdog, _NOTCH_NEUTRAL, _MAX_NOTCH


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state(**overrides) -> TrainState:
    defaults: dict[str, Any] = dict(
        speed_mph=40.0, limit_mph=50.0, target_mph=0.0,
        handle_notch=4, acceleration_ms2=None, gradient_pct=0.0,
        rain_intensity=0.0, next_limit_mph=None, distance_next_m=None,
        brake_marker_m=None, speed_limits_ahead=None, supervision="csm",
        ack_required=False, stations=None, doors_open=False, doors_telem=None,
        doors_dmi=None,
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

    def test_brake_fast_jumps_to_neutral(self):
        c = _fresh()
        assert c._target_notch(BRAKE_FAST, 7) == 4
        assert c._target_notch(BRAKE_FAST, 5) == 4
        assert c._target_notch(BRAKE_FAST, 4) == 3
        assert c._target_notch(BRAKE_FAST, 1) == 1

    def test_emergency_goes_to_notch_zero(self):
        c = _fresh()
        assert c._target_notch(EMERGENCY, 6) == 4
        assert c._target_notch(EMERGENCY, 4) == 0
        assert c._target_notch(EMERGENCY, 2) == 0


# ── HOLD/PAUSED ───────────────────────────────────────────────────────────────

class TestHoldPaused:
    def test_hold_returns_false(self):
        c = _fresh()
        s = _state()
        assert c.execute(HOLD, s, None, None) is False

    def test_paused_returns_false(self):
        c = _fresh()
        s = _state()
        assert c.execute(PAUSED, s, None, None) is False


# ── Rate limiting ─────────────────────────────────────────────────────────────

class TestRateLimit:
    def test_rate_limit_blocks_second_call(self):
        c = HandleController()
        hwnd = MagicMock()

        with patch("tsw6.autopilot.handle_controller.send_key"):
            s = _state(handle_notch=6)
            c.execute(COAST, s, None, hwnd)
            result = c.execute(COAST, s, None, hwnd)
        assert result is False

    def test_brake_fast_uses_shorter_interval(self):
        """BRAKE_FAST tiene intervalo más corto que COAST."""
        from tsw6.governor.governor_constants import CONTROL_INTERVAL_BRAKE, CONTROL_INTERVAL_FAST
        assert CONTROL_INTERVAL_FAST < CONTROL_INTERVAL_BRAKE


# ── IPC reintentos ────────────────────────────────────────────────────────────

class TestIpcRetries:
    def test_rpc_retries_before_fail(self):
        c = _fresh()
        conn = MagicMock()
        conn.set_control_value.side_effect = [False, False, True]

        with patch("tsw6.autopilot.handle_controller.time.sleep"):
            ok = c._try_rpc(conn, "PowerBrakeHandle", 0.375)

        assert ok is True
        assert conn.set_control_value.call_count == 3
        assert c._rpc_fail_count == 0

    def test_rpc_short_disable_after_many_failures(self):
        from tsw6.autopilot.handle_controller import (
            _RPC_DISABLE_COUNT,
            _RPC_DISABLE_S,
        )

        c = _fresh()
        conn = MagicMock()
        conn.set_control_value.return_value = False

        with patch("tsw6.autopilot.handle_controller.time.sleep"):
            for _ in range(_RPC_DISABLE_COUNT):
                assert c._try_rpc(conn, "PowerBrakeHandle", 0.5) is False

        assert c._rpc_disabled_until > 0
        assert _RPC_DISABLE_S <= 10.0


# ── Teclado (mock hwnd) ───────────────────────────────────────────────────────

class TestKeyboard:
    def test_coast_sends_vk_d(self):
        from tsw6.autopilot.handle_controller import VK_D
        from tsw6.autopilot.tsw_keys import KEY_TAP_MS
        c = _fresh()
        s = _state(handle_notch=6)  # quiere bajar a 5
        hwnd = MagicMock()

        with patch("tsw6.autopilot.handle_controller.send_key") as mock_send:
            result = c.execute(COAST, s, None, hwnd)
        assert result is True
        mock_send.assert_called_once_with(hwnd, VK_D, hold_ms=KEY_TAP_MS)

    def test_no_hwnd_returns_false(self):
        c = _fresh()
        s = _state(handle_notch=6)
        result = c.execute(COAST, s, None, None)
        assert result is False

    def test_coast_when_already_neutral_no_send(self):
        """COAST en neutro no debe enviar nada (target == current)."""
        c = _fresh()
        s = _state(handle_notch=4)  # ya en neutro

        with patch("tsw6.autopilot.handle_controller.send_key") as mock_send:
            result = c.execute(COAST, s, None, 1)
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
        with patch("tsw6.autopilot.handle_controller.send_key") as mock_send:
            result = c.execute(COAST, s, None, 1)
        assert result is False
        mock_send.assert_not_called()

    def test_coast_not_suppressed_for_plus_one_jump(self):
        """Salto de +1 es nuestro propio comando — NO activa supresión."""
        c = _fresh()
        c._last_seen_notch = 4
        # Simular: _last_ext_up_t queda del pasado (no fue detectado como externo)
        c._last_ext_up_t = 0.0

        s = _state(handle_notch=5, ack_required=False)
        with patch("tsw6.autopilot.handle_controller.send_key") as mock_send:
            result = c.execute(COAST, s, None, 1)
        assert result is True

    def test_coast_allowed_after_grace_period(self):
        c = _fresh()
        c._last_ext_up_t = time.time() - 2.0  # hace 2s (> 1.5s de gracia)

        s = _state(handle_notch=6, ack_required=False)
        with patch("tsw6.autopilot.handle_controller.send_key") as mock_send:
            result = c.execute(COAST, s, None, 1)
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
        """Exceso >= 5mph durante >= 3s → BRAKE_FAST."""
        w = SafetyWatchdog()
        # Exceso inmediato
        s = _state(speed_mph=57.0, limit_mph=50.0, acceleration_ms2=0.1)
        w.check(s)
        # Forzar que el timer de inicio sea hace 4s
        w._overspeed_since = time.time() - 4.0

        result = w.check(s)
        assert result == BRAKE_FAST

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


class TestDastscDirectNotch:
    def test_ipc_applies_one_step_toward_brake_command(self):
        from tsw6.braking.v2.command import BrakeCommand

        c = _fresh()
        conn = MagicMock(spec=["mode", "has_control_api", "set_control_value"])
        conn.mode = "ue4ss"
        conn.has_control_api.return_value = True
        conn.set_control_value.return_value = True

        cmd = BrakeCommand(kind="APPLY", target_notch=2, phase="B2")
        s = _state(handle_notch=4)

        assert c.execute("BRAKE", s, conn, None, brake_command=cmd) is True
        conn.set_control_value.assert_called_once()
        args = conn.set_control_value.call_args[0]
        assert args[0] == "PowerBrakeHandle"
        assert abs(args[1] - 0.375) < 0.01

    def test_apply_uses_ipc_with_hwnd_when_available(self):
        from tsw6.braking.v2.command import BrakeCommand

        c = _fresh()
        conn = MagicMock(spec=["mode", "has_control_api", "set_control_value"])
        conn.mode = "ue4ss"
        conn.has_control_api.return_value = True
        conn.set_control_value.return_value = True

        cmd = BrakeCommand(kind="APPLY", target_notch=2, phase="B2")
        s = _state(handle_notch=4)
        hwnd = MagicMock()

        with patch("tsw6.autopilot.handle_controller.send_key") as mock_key:
            assert c.execute("BRAKE", s, conn, hwnd, brake_command=cmd) is True
            mock_key.assert_not_called()
            conn.set_control_value.assert_called_once()
            assert abs(conn.set_control_value.call_args[0][1] - 0.375) < 0.01

    def test_apply_uses_async_enqueue_when_available(self):
        from tsw6.braking.v2.command import BrakeCommand

        c = _fresh()
        conn = MagicMock(
            spec=["mode", "has_control_api", "enqueue_control_value"])
        conn.mode = "ue4ss"
        conn.has_control_api.return_value = True
        conn.enqueue_control_value.return_value = True

        cmd = BrakeCommand(kind="APPLY", target_notch=2, phase="B2")
        s = _state(handle_notch=4)

        assert c.execute("BRAKE", s, conn, None, brake_command=cmd) is True
        conn.enqueue_control_value.assert_called_once()
        assert abs(conn.enqueue_control_value.call_args[0][1] - 0.375) < 0.01

    def test_apply_p1_no_keyboard_when_ipc_fails(self):
        """P1 (BrakeCommand): sin fallback teclado — Fase B."""
        from tsw6.braking.v2.command import BrakeCommand

        c = _fresh()
        conn = MagicMock(spec=["mode", "has_control_api", "set_control_value"])
        conn.mode = "ue4ss"
        conn.has_control_api.return_value = True
        conn.set_control_value.return_value = False

        cmd = BrakeCommand(kind="APPLY", target_notch=2, phase="B2")
        s = _state(handle_notch=4)
        hwnd = MagicMock()

        with patch("tsw6.autopilot.handle_controller.send_key") as mock_key:
            assert c.execute("BRAKE", s, conn, hwnd, brake_command=cmd) is False
            mock_key.assert_not_called()

    def test_legacy_path_falls_back_to_keyboard_when_ipc_fails(self):
        """Acciones legacy (sin BrakeCommand) sí pueden usar teclado."""
        c = _fresh()
        conn = MagicMock(spec=["mode", "has_control_api", "set_control_value"])
        conn.mode = "ue4ss"
        conn.has_control_api.return_value = True
        conn.set_control_value.return_value = False

        s = _state(handle_notch=6)
        hwnd = MagicMock()

        with patch("tsw6.autopilot.handle_controller.send_key") as mock_key:
            assert c.execute("COAST", s, conn, hwnd) is True
            mock_key.assert_called_once()

    def test_release_uses_ipc_to_neutral_even_with_hwnd(self):
        from tsw6.braking.v2.command import BrakeCommand

        c = _fresh()
        conn = MagicMock(spec=["mode", "has_control_api", "set_control_value"])
        conn.mode = "ue4ss"
        conn.has_control_api.return_value = True
        conn.set_control_value.return_value = True

        cmd = BrakeCommand(kind="RELEASE", target_notch=4)
        s = _state(handle_notch=3)
        hwnd = MagicMock()

        with patch("tsw6.autopilot.handle_controller.send_key") as mock_key:
            assert c.execute("RELEASE", s, conn, hwnd, brake_command=cmd) is True
            mock_key.assert_not_called()
            conn.set_control_value.assert_called_once()
            assert abs(conn.set_control_value.call_args[0][1] - 0.5) < 0.01

    def test_hold_still_executes_brake_command(self):
        from tsw6.braking.v2.command import BrakeCommand

        c = _fresh()
        conn = MagicMock(spec=["mode", "has_control_api", "set_control_value"])
        conn.mode = "ue4ss"
        conn.has_control_api.return_value = True
        conn.set_control_value.return_value = True
        cmd = BrakeCommand(kind="APPLY", target_notch=2, phase="B2")
        s = _state(handle_notch=5)
        hwnd = MagicMock()

        with patch("tsw6.autopilot.handle_controller.send_key") as mock_key:
            assert c.execute("HOLD", s, conn, hwnd, brake_command=cmd) is True
            mock_key.assert_not_called()
            conn.set_control_value.assert_called_once()


class TestKeyboardTelemetryWait:
    def test_no_second_key_until_notch_changes(self):
        from tsw6.braking.v2.command import BrakeCommand

        c = _fresh()
        conn = MagicMock(spec=["prefer_keyboard_actuator"])
        conn.prefer_keyboard_actuator.return_value = True
        hwnd = MagicMock()
        cmd = BrakeCommand(kind="APPLY", target_notch=3, phase="B1")
        s = _state(handle_notch=4)

        with patch("tsw6.autopilot.handle_controller.send_key") as mock_key:
            assert c.execute("BRAKE", s, conn, hwnd, brake_command=cmd) is True
            assert c.execute("BRAKE", s, conn, hwnd, brake_command=cmd) is False
            mock_key.assert_called_once()

            s2 = _state(handle_notch=3)
            c._last_control = 0.0
            assert c.execute("BRAKE", s2, conn, hwnd, brake_command=cmd) is False
            mock_key.assert_called_once()

    def test_p1_uses_keyboard_when_driver_input_dead(self):
        from tsw6.braking.v2.command import BrakeCommand
        from tsw6.autopilot.tsw_keys import KEY_TAP_MS

        c = _fresh()
        conn = MagicMock(
            spec=["mode", "has_control_api", "enqueue_control_value",
                  "prefer_keyboard_actuator"])
        conn.mode = "ue4ss"
        conn.has_control_api.return_value = True
        conn.prefer_keyboard_actuator.return_value = True
        hwnd = MagicMock()
        cmd = BrakeCommand(kind="APPLY", target_notch=3, phase="B1")
        s = _state(handle_notch=4)

        with patch("tsw6.autopilot.handle_controller.send_key") as mock_key:
            from tsw6.autopilot.handle_controller import VK_D
            assert c.execute("BRAKE", s, conn, hwnd, brake_command=cmd) is True
            mock_key.assert_called_once_with(hwnd, VK_D, hold_ms=KEY_TAP_MS)
            conn.enqueue_control_value.assert_not_called()
