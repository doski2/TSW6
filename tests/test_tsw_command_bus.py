"""Tests tsw_command_bus.py — V2.1 (mock cliente, sin juego)."""

import unittest
from unittest.mock import MagicMock

from tsw6.telemetry.tsw_command_bus import (
    clamp_brake_value,
    combined_axis_to_notch,
    combined_notch_to_axis,
    combined_notch_to_value,
    dispatch_brake,
    dispatch_combined_notch,
    is_allowed_brake_path,
    neutral_combined_value,
    resolve_brake_path,
)


class TestCommandBusValidation(unittest.TestCase):
    def test_allows_power_brake(self):
        self.assertTrue(is_allowed_brake_path("PowerBrakeHandle"))

    def test_blocks_emergency(self):
        self.assertFalse(is_allowed_brake_path("EmergencyBrake"))

    def test_blocks_throttle(self):
        self.assertFalse(is_allowed_brake_path("Throttle"))

    def test_resolve_logical_axis(self):
        self.assertEqual(resolve_brake_path("combined_brake"), "PowerBrakeHandle")
        self.assertEqual(resolve_brake_path("train_brake"), "AutomaticBrake")

    def test_resolve_from_schema(self):
        schema = {"tsw_api_paths": {"combined_brake": "CustomHandle"}}
        self.assertEqual(resolve_brake_path("combined_brake", schema), "CustomHandle")


class TestClampAndNotch(unittest.TestCase):
    def test_combined_notch_scale(self):
        self.assertEqual(combined_notch_to_value(0), 0.0)
        self.assertEqual(combined_notch_to_value(4), 0.5)
        self.assertEqual(combined_notch_to_value(8), 1.0)

    def test_class323_input_detents(self):
        self.assertEqual(combined_notch_to_axis(0), -1.0)
        self.assertEqual(combined_notch_to_axis(1), -0.6)
        self.assertEqual(combined_notch_to_axis(2), -0.4)
        self.assertEqual(combined_notch_to_axis(3), -0.2)
        self.assertEqual(combined_notch_to_axis(4), 0.0)
        self.assertEqual(combined_notch_to_axis(5), 0.25)
        self.assertEqual(combined_notch_to_axis(8), 1.0)
        self.assertEqual(combined_axis_to_notch(-0.6), 1)
        self.assertEqual(combined_axis_to_notch(-0.4), 2)
        self.assertEqual(combined_axis_to_notch(0.75), 7)

    def test_neutral(self):
        self.assertEqual(neutral_combined_value(), 0.5)

    def test_clamp_ind_brake(self):
        self.assertEqual(clamp_brake_value("IndependentBrake", -2.0), -1.0)
        self.assertEqual(clamp_brake_value("IndependentBrake", 0.5), 0.5)

    def test_clamp_auto_brake(self):
        self.assertEqual(clamp_brake_value("AutomaticBrake", 1.5), 1.0)


class TestDispatchBrake(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.set_input_value.return_value = {
            "ok": True, "path": "PowerBrakeHandle", "value": -0.4,
        }
        self.client.set_value.return_value = {"ok": True, "path": "PowerBrakeHandle", "value": 0.25}
        self.client.get_input_value.return_value = None
        self.client.read_hud_combined_notch.return_value = 2

    def test_dispatch_combined_brake(self):
        result = dispatch_brake(self.client, "combined_brake", 0.25)
        self.assertTrue(result["ok"])
        self.assertEqual(result["path"], "PowerBrakeHandle")
        self.client.set_input_value.assert_called_once_with(
            "PowerBrakeHandle", -0.4, timeout=None)
        self.client.set_value.assert_not_called()

    def test_dispatch_combined_brake_falls_back_to_value(self):
        self.client.set_input_value.return_value = {"ok": False}
        self.client.read_hud_combined_notch.return_value = 2
        result = dispatch_brake(self.client, "combined_brake", 0.25)
        self.assertTrue(result["ok"])
        self.client.set_value.assert_called_once_with(
            "PowerBrakeHandle", 0.25, timeout=None)

    def test_dispatch_rejects_emergency(self):
        result = dispatch_brake(self.client, "EmergencyBrake", 1.0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "command_not_allowed")
        self.client.set_value.assert_not_called()

    def test_dispatch_unknown_axis(self):
        result = dispatch_brake(self.client, "unknown_axis", 0.5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unknown_control")

    def test_dispatch_combined_notch_shortcut(self):
        result = dispatch_combined_notch(self.client, 2)  # freno B2 ≈ 0.25
        self.assertTrue(result["ok"])
        self.client.set_input_value.assert_called_once_with(
            "PowerBrakeHandle", -0.4, timeout=None)

    def test_dispatch_clamps_high_value(self):
        dispatch_brake(self.client, "AutomaticBrake", 9.0)
        self.client.set_value.assert_called_once_with(
            "AutomaticBrake", 1.0, timeout=None)


if __name__ == "__main__":
    unittest.main()
