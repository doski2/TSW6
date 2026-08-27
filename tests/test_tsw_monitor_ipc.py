"""Tests del modo test-ipc del monitor (sin juego)."""

from __future__ import annotations

import sys
from unittest.mock import patch

from tsw6.telemetry.tsw_monitor import _parse_args, _probe_is_fresh
from tsw6.telemetry.tsw_ue4ss_reader import ProbeSnapshot


def test_parse_args_accepts_test_ipc() -> None:
    with patch.object(sys, "argv", ["tsw_monitor.py", "test-ipc"]):
        modo, interval = _parse_args()
    assert modo == "test-ipc"
    assert interval > 0


def test_parse_args_test_ipc_underscore() -> None:
    with patch.object(sys, "argv", ["tsw_monitor.py", "test_ipc"]):
        modo, _ = _parse_args()
    assert modo == "test-ipc"


def test_probe_is_fresh_requires_seq_and_speed() -> None:
    assert not _probe_is_fresh(None)
    assert not _probe_is_fresh(ProbeSnapshot(seq=None, speed_ms=1.0))
    snap = ProbeSnapshot(seq=10, speed_ms=5.0)
    with patch("tsw6.telemetry.tsw_monitor.default_getdata_path") as gp:
        gp.return_value.is_file.return_value = True
        gp.return_value.stat.return_value.st_mtime = __import__("time").time()
        assert _probe_is_fresh(snap)
