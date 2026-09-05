from __future__ import annotations

import _path  # noqa: F401

import json
from pathlib import Path

from tsw6v2.loop import AgentSnapshot
from tsw6v2.trace import JsonlTrace, format_investigate, session_meta


def test_format_investigate():
    snap = AgentSnapshot(
        tick=12,
        speed_mph=58.2,
        lever_notch=4,
        target_notch=3,
        limit_mph=55.0,
        limit_dist_m=340.0,
        effective_limit_mph=60.0,
        p1_cmd="APPLY",
        p1_phase="B1",
        p1_dist_start_m=12.0,
        p1_apply_now=True,
        p1_detail="Límite 55 mph",
        p1_reason="plan",
        ipc_sent=True,
    )
    line = format_investigate(snap)
    assert "tick=12" in line
    assert "lim=55@340" in line
    assert "p1=APPLY/B1" in line
    assert "apply=Y" in line
    assert "why=plan" in line


def test_format_investigate_brake_air_fields():
    snap = AgentSnapshot(
        tick=3,
        speed_mph=50.0,
        brake_cyl_bar=2.8,
        brake_fill_s=2.1,
    )
    line = format_investigate(snap)
    assert "P=2.8bar" in line
    assert "fill=2.1s" in line


def test_jsonl_trace(tmp_path: Path):
    path = tmp_path / "t.jsonl"
    trace = JsonlTrace(path, session_meta(mode="limit-brake", route="test"))
    snap = AgentSnapshot(
        tick=1,
        seq=10,
        speed_mph=50.0,
        lever_notch=3,
        target_notch=3,
        limit_mph=45.0,
        limit_dist_m=100.0,
        effective_limit_mph=50.0,
        p1_cmd="APPLY",
        p1_phase="B1",
        p1_apply_now=True,
        vehicle="Class 323",
        brake_cyl_bar=3.2,
        brake_fill_s=2.4,
    )
    trace.write_tick(snap, t_ms=50.0, ipc_cmd_id=1)
    trace.close()

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    session = json.loads(lines[0])
    assert session["type"] == "session"
    assert session["mode"] == "limit-brake"
    tick = json.loads(lines[1])
    assert tick["type"] == "tick"
    assert tick["spd_mph"] == 50.0
    assert tick["p1"]["cmd"] == "APPLY"
    assert tick["ipc"]["cmd_id"] == 1
    assert tick["brake_cyl_bar"] == 3.2
    assert tick["brake_fill_s"] == 2.4


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
