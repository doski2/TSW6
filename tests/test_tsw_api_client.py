"""Tests tsw_api_client.py — V2.0 (mock HTTP, sin juego)."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tsw6.telemetry.tsw_api_client import (
    TswApiClient,
    encode_control_path,
    find_api_key,
    get_key_path,
)


class TestEncodeControlPath(unittest.TestCase):
    def test_simple_path(self):
        self.assertEqual(encode_control_path("PowerBrakeHandle"), "PowerBrakeHandle")

    def test_space_in_path(self):
        self.assertEqual(
            encode_control_path("VirtualRailDriver.Auto Brake"),
            "VirtualRailDriver.Auto%20Brake",
        )


class TestTswApiClient(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.client = TswApiClient("test-key-abc", session=self.session)

    def test_set_value_success(self):
        resp = MagicMock()
        resp.status_code = 200
        self.session.patch.return_value = resp

        out = self.client.set_value("PowerBrakeHandle", 0.25)
        self.assertTrue(out["ok"])
        self.assertEqual(out["path"], "PowerBrakeHandle")
        self.assertEqual(out["value"], 0.25)
        call_url = self.session.patch.call_args[0][0]
        self.assertIn("/set/PowerBrakeHandle.Value", call_url)
        self.assertEqual(
            self.session.patch.call_args[1]["headers"]["DTGCommKey"],
            "test-key-abc",
        )

    def test_set_value_connection_error(self):
        import requests
        self.session.patch.side_effect = requests.exceptions.ConnectionError()
        out = self.client.set_value("AutomaticBrake", 0.5)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "connection_refused")

    def test_get_value_numeric(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = 0.375
        self.session.get.return_value = resp
        self.assertEqual(self.client.get_value("PowerBrakeHandle"), 0.375)

    def test_probe_info(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"Meta": {"APIVersion": 1}}
        self.session.get.return_value = resp
        self.assertTrue(self.client.probe())

    def test_get_node_success(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "Result": "Success",
            "Values": {"Speed (ms)": 12.5},
        }
        self.session.get.return_value = resp
        out = self.client.get_node("CurrentDrivableActor.Function.HUD_GetSpeed")
        self.assertEqual(out, {"Speed (ms)": 12.5})
        call_path = self.session.get.call_args[0][0]
        self.assertIn("/get/CurrentDrivableActor.Function.HUD_GetSpeed", call_path)

    def test_get_node_error(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"Result": "Error", "Message": "nope"}
        self.session.get.return_value = resp
        self.assertIsNone(self.client.get_node("Missing.Node"))


class TestFindApiKey(unittest.TestCase):
    def test_missing_key_returns_none(self):
        with patch("tsw6.telemetry.tsw_api_client.KEY_PATHS", (Path("/nonexistent/key.txt"),)):
            self.assertIsNone(find_api_key())
            self.assertIsNone(get_key_path())


if __name__ == "__main__":
    unittest.main()
