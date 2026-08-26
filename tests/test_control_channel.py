"""Tests para TelemetryReader y AsyncCommandWriter (Fase A)."""

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
