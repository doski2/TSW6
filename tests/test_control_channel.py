"""Tests para TelemetryReader y AsyncCommandWriter (Fase A/B)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from tsw6.telemetry.control_channel import (
    AsyncCommandWriter,
    TelemetryReader,
)
from tsw6.telemetry.tsw_ipc_bus import adaptive_ack_timeout_s, parse_send_ack_line
from tsw6.telemetry.tsw_ue4ss_reader import ProbeSnapshot


def _write_getdata(path: Path, seq: int, speed: float = 10.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"seq={seq} speed_ms={speed} power=0 power_neg=0 handle_notch=4 "
        f"lever_notch=4 train_brake=0 loco_brake=0 dyn_brake=0 accel_ms2=0 "
        f"vehicle=Test"
    )
    path.write_text(line + "\n", encoding="utf-8")


class TestTelemetryReader:
    def test_reads_snapshot_in_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "GetData.txt"
            _write_getdata(path, seq=1)
            reader = TelemetryReader(path, hz=50.0)
            reader.start()
            try:
                deadline = time.monotonic() + 2.0
                snap = None
                while time.monotonic() < deadline:
                    snap, age = reader.get_snapshot()
                    if snap is not None and snap.seq == 1:
                        break
                    time.sleep(0.02)
                assert snap is not None
                assert snap.seq == 1
                assert age >= 0.0
                _write_getdata(path, seq=2, speed=12.0)
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    snap, _ = reader.get_snapshot()
                    if snap is not None and snap.seq == 2:
                        break
                    time.sleep(0.02)
                assert snap is not None
                assert snap.seq == 2
            finally:
                reader.stop()


class TestAsyncCommandWriter:
    def test_enqueue_returns_cmd_id(self) -> None:
        writer = AsyncCommandWriter()
        with patch(
            "tsw6.telemetry.control_channel.dispatch_ipc_combined_notch",
            return_value={"ok": True, "ack_ms": 15.0},
        ):
            writer.start()
            try:
                cmd_id = writer.enqueue_combined_notch(3)
                assert cmd_id == 1
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    st = writer.state()
                    if not st.pending and st.last_ok:
                        break
                    time.sleep(0.02)
                st = writer.state()
                assert st.last_ok is True
                assert st.target_notch == 3
                assert st.last_ack_ms == 15.0
                assert st.last_via == "ipc"
                assert st.ipc_ok == 1
            finally:
                writer.stop()

    def test_queue_full_drops(self) -> None:
        writer = AsyncCommandWriter(max_queue=1)
        with patch(
            "tsw6.telemetry.control_channel.dispatch_ipc_combined_notch",
            side_effect=lambda *a, **k: (
                time.sleep(0.2) or {"ok": True, "ack_ms": 1.0}
            ),
        ):
            writer.start()
            try:
                assert writer.enqueue_combined_notch(3) == 1
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    if writer.state().inflight:
                        break
                    time.sleep(0.01)
                assert writer.enqueue_combined_notch(2) == 2
                dropped = writer.enqueue_combined_notch(1)
                assert dropped == 0
                assert writer.state().drops >= 1
            finally:
                writer.stop()

    def test_retries_on_ipc_failure(self) -> None:
        calls = {"n": 0}

        def _dispatch(*_a, **_k):
            calls["n"] += 1
            if calls["n"] < 2:
                return {"ok": False, "error": "ack_timeout", "ack_ms": 80.0}
            return {"ok": True, "ack_ms": 22.0}

        writer = AsyncCommandWriter(max_attempts=3)
        with patch(
            "tsw6.telemetry.control_channel.dispatch_ipc_combined_notch",
            side_effect=_dispatch,
        ):
            writer.start()
            try:
                writer.enqueue_combined_notch(2)
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    st = writer.state()
                    if st.last_ok and not st.pending:
                        break
                    time.sleep(0.02)
                st = writer.state()
                assert st.last_ok is True
                assert st.retries >= 1
                assert calls["n"] >= 2
            finally:
                writer.stop()

    def test_on_ipc_fail_callback(self) -> None:
        seen: list[str] = []

        writer = AsyncCommandWriter(
            on_ipc_fail=lambda err: seen.append(err),
            max_attempts=1,
        )
        with patch(
            "tsw6.telemetry.control_channel.dispatch_ipc_combined_notch",
            return_value={"ok": False, "error": "lua_rejected", "ack_ms": 12.0},
        ):
            writer.start()
            try:
                writer.enqueue_combined_notch(2)
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    if seen:
                        break
                    time.sleep(0.02)
                assert seen == ["lua_rejected"]
                assert writer.state().last_via != "http"
            finally:
                writer.stop()

    def test_telem_correlation(self) -> None:
        writer = AsyncCommandWriter()
        writer.enqueue_combined_notch(3)
        writer.update_telem_correlation(1, True, 3)
        st = writer.state()
        assert st.confirmed_cmd_id == 1
        assert st.reached_notch is True


class TestAdaptiveAck:
    def test_default_frame_budget(self) -> None:
        t = adaptive_ack_timeout_s([])
        assert 0.05 <= t <= 0.12

    def test_grows_with_recent_acks(self) -> None:
        base = adaptive_ack_timeout_s([])
        high = adaptive_ack_timeout_s([80.0, 85.0, 90.0, 88.0])
        assert high >= base

    def test_parse_ack_with_cmd_id(self) -> None:
        ack = parse_send_ack_line("PowerBrakeHandle:0.2500:ok:42")
        assert ack is not None
        assert ack["ok"] is True
        assert ack["cmd_id"] == 42
        assert abs(ack["value"] - 0.25) < 0.001
