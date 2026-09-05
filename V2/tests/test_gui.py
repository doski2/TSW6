from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.gui import format_viewer_lines
from tsw6v2.loop import AgentSnapshot


def test_format_viewer_lines_empty() -> None:
    assert format_viewer_lines(None) == ["(sin GetData)"]


def test_format_viewer_lines_snapshot() -> None:
    snap = AgentSnapshot(
        tick=5,
        seq=10,
        speed_mph=22.0,
        lever_notch=4,
        target_notch=3,
        vehicle="Class323",
        train_brake=0.1,
    )
    lines = format_viewer_lines(snap, loop_hz=18.5)
    assert len(lines) == 3
    assert "seq=10" in lines[0]
    assert "22.0 mph" in lines[1]
    assert "Class323" in lines[2]


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
