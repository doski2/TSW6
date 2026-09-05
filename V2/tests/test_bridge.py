from __future__ import annotations

import _path  # noqa: F401

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from tsw6v2.bridge.commands import combined_notch_to_value
from tsw6v2.bridge.getdata import (
    ProbeSnapshot,
    parse_probe_line,
    power_to_combined_notch,
    read_probe_file,
)
from tsw6v2.bridge.ipc_bus import (
    APPLY_FLAG_FILENAME,
    SEND_COMMAND_FILENAME,
    dispatch_ipc_combined_notch,
    format_send_command_line,
    parse_send_ack_line,
    purge_lua_commands,
    write_send_command,
    write_send_command_with_ack,
)


class TestCommands:
    def test_combined_notch_scale(self) -> None:
        assert combined_notch_to_value(0) == 0.0
        assert combined_notch_to_value(4) == 0.5
        assert combined_notch_to_value(8) == 1.0
        assert combined_notch_to_value(3) == 0.375


class TestGetData:
    def test_parse_probe_line(self) -> None:
        line = (
            "seq=42 speed_ms=12.34 power=3 power_neg=0 train_brake=0.1 "
            "lever_notch=4 handle_notch=4 vehicle=Class323"
        )
        data = parse_probe_line(line)
        assert data["seq"] == 42
        assert data["speed_ms"] == 12.34
        assert data["lever_notch"] == 4

    def test_brake_cyl_bar_from_lab_fixture(self) -> None:
        fixture = Path(__file__).resolve().parents[2] / "tests/fixtures/lab/probe_line_323.txt"
        line = fixture.read_text(encoding="utf-8").strip()
        snap = ProbeSnapshot.from_dict(parse_probe_line(line))
        assert snap.brake_cyl_bar is not None
        assert snap.brake_cyl_bar == pytest.approx(4.283247188, rel=1e-6)

    def test_brake_cyl_bar_question_is_none(self) -> None:
        data = parse_probe_line("seq=1 speed_ms=0 brake_cyl_bar=? vehicle=Class323")
        assert data["brake_cyl_bar"] is None

    def test_lever_notch_float(self) -> None:
        data = parse_probe_line("seq=1 lever_notch=4.0000 speed_ms=0 vehicle=Class323")
        assert data["lever_notch"] == 4
        snap = ProbeSnapshot.from_dict(data)
        assert snap.combined_handle_notch() == 4

    def test_power_to_notch(self) -> None:
        assert power_to_combined_notch(0) == 4
        assert power_to_combined_notch(-3) == 1

    def test_signal_red(self) -> None:
        data = parse_probe_line(
            "seq=10 speed_ms=15 signal_red=1 signal_dist_cm=8420.5 vehicle=Class323"
        )
        snap = ProbeSnapshot.from_dict(data)
        assert snap.signal_red is True
        assert snap.signal_dist_cm == 8420.5

    def test_read_probe_file(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        gd.write_text("seq=1 speed_ms=10 lever_notch=3 vehicle=Class323\n", encoding="utf-8")
        snap = read_probe_file(gd)
        assert snap is not None
        assert snap.combined_handle_notch() == 3


class TestIpcBus:
    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._env = mock.patch.dict(
            os.environ, {"TEMP": self._tmpdir, "TMP": self._tmpdir}, clear=False
        )
        self._env.start()

    def teardown_method(self) -> None:
        self._env.stop()

    def test_format_line(self) -> None:
        assert format_send_command_line("combined_brake", 0.25) == "PowerBrakeHandle:0.2500"

    def test_format_line_cmd_id(self) -> None:
        assert format_send_command_line("combined_brake", 0.25, cmd_id=42) == (
            "PowerBrakeHandle:0.2500:42"
        )

    def test_parse_ack(self) -> None:
        ack = parse_send_ack_line("PowerBrakeHandle:0.3750:ok:7")
        assert ack is not None
        assert ack["ok"] is True
        assert ack["cmd_id"] == 7

    def test_write_and_purge(self) -> None:
        assert write_send_command("combined_brake", 0.5)
        bridge = Path(self._tmpdir) / "TSW6Bridge"
        assert (bridge / SEND_COMMAND_FILENAME).is_file()
        assert (bridge / APPLY_FLAG_FILENAME).is_file()
        assert purge_lua_commands()

    def test_dispatch_combined_notch(self) -> None:
        with mock.patch(
            "tsw6v2.bridge.ipc_bus.wait_send_ack",
            return_value={"name": "PowerBrakeHandle", "value": 0.25, "ok": True},
        ):
            result = dispatch_ipc_combined_notch(2)
        assert result["ok"] is True
        assert result["path"] == "PowerBrakeHandle"

    def test_ack_timeout(self) -> None:
        with mock.patch("tsw6v2.bridge.ipc_bus.wait_send_ack", return_value=None):
            result = dispatch_ipc_combined_notch(2)
        assert result["ok"] is False
        assert result["error"] == "ack_timeout"

    def test_lua_rejected(self) -> None:
        with mock.patch(
            "tsw6v2.bridge.ipc_bus.wait_send_ack",
            return_value={"name": "PowerBrakeHandle", "value": 0.25, "ok": False},
        ):
            result = write_send_command_with_ack("combined_brake", 0.25)
        assert result["ok"] is False
        assert result["error"] == "lua_rejected"


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
