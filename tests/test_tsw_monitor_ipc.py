"""Tests del monitor v1 — solo CLI; producto → ``V2/tests/``."""

from __future__ import annotations

import sys
from unittest.mock import patch

from tsw6.telemetry.tsw_monitor import _parse_args


def test_parse_args_accepts_test_ipc() -> None:
    with patch.object(sys, "argv", ["tsw_monitor.py", "test-ipc"]):
        modo, interval = _parse_args()
    assert modo == "test-ipc"
    assert interval > 0


def test_parse_args_test_ipc_underscore() -> None:
    with patch.object(sys, "argv", ["tsw_monitor.py", "test_ipc"]):
        modo, _ = _parse_args()
    assert modo == "test-ipc"
