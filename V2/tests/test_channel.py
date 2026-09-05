from __future__ import annotations

import _path  # noqa: F401

import tempfile
import time
from pathlib import Path

from tsw6v2.channel import TelemetryReader
from tsw6v2.testdata import write_getdata_line


class TestTelemetryReader:
    def test_reads_snapshot_in_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "GetData.txt"
            write_getdata_line(path, seq=1, lever=4)
            reader = TelemetryReader(path, hz=50.0)
            reader.start()
            try:
                deadline = time.monotonic() + 2.0
                snap = None
                while time.monotonic() < deadline:
                    snap, _age = reader.get_snapshot()
                    if snap is not None and snap.seq == 1:
                        break
                    time.sleep(0.02)
                assert snap is not None
                assert snap.seq == 1
                write_getdata_line(path, seq=2, lever=3, speed_ms=12.0)
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


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
