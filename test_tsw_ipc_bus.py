"""Tests tsw_ipc_bus.py — SendCommand IPC (sin juego)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tsw_ipc_bus import (
    APPLY_FLAG_FILENAME,
    SEND_COMMAND_FILENAME,
    dispatch_ipc_brake,
    dispatch_ipc_combined_notch,
    enable_lua_commands,
    format_send_command_line,
    purge_lua_commands,
    release_controls,
    write_send_command,
)


class TestIpcBus(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._env = mock.patch.dict(
            os.environ, {"TEMP": self._tmpdir, "TMP": self._tmpdir}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def _bridge(self) -> Path:
        return Path(self._tmpdir) / "TSW6Bridge"

    def test_format_line(self):
        line = format_send_command_line("combined_brake", 0.25)
        self.assertEqual(line, "PowerBrakeHandle:0.2500")

    def test_write_and_flag(self):
        self.assertTrue(write_send_command("PowerBrakeHandle", 0.5))
        bridge = self._bridge()
        self.assertTrue((bridge / SEND_COMMAND_FILENAME).is_file())
        self.assertTrue((bridge / APPLY_FLAG_FILENAME).is_file())
        text = (bridge / SEND_COMMAND_FILENAME).read_text(encoding="utf-8")
        self.assertIn("PowerBrakeHandle:0.5000", text)

    def test_dispatch_rejects_emergency(self):
        result = dispatch_ipc_brake("EmergencyBrake", 1.0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "command_not_allowed")

    def test_dispatch_combined_notch(self):
        result = dispatch_ipc_combined_notch(2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["path"], "PowerBrakeHandle")
        self.assertAlmostEqual(result["value"], 0.25)

    def test_purge_removes_files(self):
        enable_lua_commands()
        write_send_command("PowerBrakeHandle", 0.5)
        self.assertTrue(purge_lua_commands())
        bridge = self._bridge()
        self.assertFalse((bridge / SEND_COMMAND_FILENAME).exists())
        self.assertFalse((bridge / APPLY_FLAG_FILENAME).exists())

    def test_release_controls(self):
        write_send_command("PowerBrakeHandle", 0.0)
        with mock.patch("tsw_ipc_bus.time.sleep"):
            release_controls(wait_s=0.0)
        bridge = self._bridge()
        self.assertFalse((bridge / APPLY_FLAG_FILENAME).exists())


if __name__ == "__main__":
    unittest.main()
