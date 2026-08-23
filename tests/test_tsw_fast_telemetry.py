"""Tests tsw_fast_telemetry.py — mock HTTP."""

import unittest
from unittest.mock import MagicMock

from tsw6.telemetry.tsw_fast_telemetry import CONTROL_PATHS, FastControlReader
from tsw6.telemetry.tsw_api_client import TswApiClient


class TestFastControlReader(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.client = TswApiClient("key", session=self.session)

    def test_read_subscription_parses_entries(self):
        reader = FastControlReader(self.client, subscription_id=7)
        reader._use_subscription = True
        self.session.get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "Entries": [
                    {
                        "Path": CONTROL_PATHS[0],
                        "NodeValid": True,
                        "Values": {"Speed (ms)": 10.0},
                    },
                    {
                        "Path": CONTROL_PATHS[1],
                        "NodeValid": True,
                        "Values": {"Power": 0.5, "IsNegative": False},
                    },
                ]
            },
        )
        snap = reader.read()
        self.assertEqual(snap.speed_ms, 10.0)
        self.assertEqual(snap.power, 0.5)
        self.assertEqual(snap.source, "subscription")

    def test_subscribe_uses_path_in_url(self):
        self.session.post.return_value = MagicMock(status_code=200, text="{}", json=lambda: {})
        ok = self.client.subscribe_path(7, CONTROL_PATHS[0])
        self.assertTrue(ok)
        url = self.session.post.call_args[0][0]
        self.assertIn("/subscription/CurrentDrivableActor.Function.HUD_GetSpeed", url)


if __name__ == "__main__":
    unittest.main()
