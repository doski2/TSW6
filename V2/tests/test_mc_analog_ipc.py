"""IPC MasterController 0..1 (Python bridge; Lua analog en M3a)."""

from __future__ import annotations

import os
import tempfile
from unittest import mock

from tsw6v2.bridge.commands import (
    combined_notch_to_value,
    master_controller_input_value,
)
from tsw6v2.bridge.ipc_bus import (
    dispatch_ipc_master_controller,
    format_send_command_line,
)


def test_master_controller_clamps_fraction() -> None:
    assert master_controller_input_value(0.0) == 0.0
    assert master_controller_input_value(1.0) == 1.0
    assert master_controller_input_value(0.72) == 0.72
    assert master_controller_input_value(1.5) == 1.0
    assert master_controller_input_value(-0.2) == 0.0


def test_mc_ipc_line_same_path_as_combined() -> None:
    line = format_send_command_line("combined_brake", 0.72)
    assert line == "PowerBrakeHandle:0.7200"


def test_notch_vs_analog_same_wire_different_semantics() -> None:
    assert combined_notch_to_value(3) == 0.375
    assert master_controller_input_value(0.375) == 0.375


def test_dispatch_ipc_master_controller() -> None:
    with mock.patch.dict(os.environ, {"TEMP": tempfile.mkdtemp()}, clear=False):
        with mock.patch(
            "tsw6v2.bridge.ipc_bus.wait_send_ack",
            return_value={"name": "PowerBrakeHandle", "value": 0.72, "ok": True, "cmd_id": 1},
        ):
            result = dispatch_ipc_master_controller(0.72, cmd_id=1)
    assert result["ok"] is True
    assert result["value"] == 0.72
    assert result["path"] == "PowerBrakeHandle"
