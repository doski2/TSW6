from __future__ import annotations

import _path  # noqa: F401

import json
from pathlib import Path

from tsw6v2.loop import AgentSnapshot
from tsw6v2.trace import (
    JsonlTrace,
    default_log_path,
    format_investigate,
    resolve_session_log_path,
    session_meta,
)


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


def test_format_investigate_station_fsm():
    snap = AgentSnapshot(
        tick=40,
        speed_mph=0.8,
        station_dist_m=18.0,
        station_fsm="STOPPED",
        p1_target_kind="LIMIT",
    )
    line = format_investigate(snap)
    assert "stn=18" in line
    assert "fsm=STOPPED" in line


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


def test_jsonl_trace_doors_fields(tmp_path: Path):
    path = tmp_path / "doors.jsonl"
    trace = JsonlTrace(path, session_meta(mode="station", route="test"))
    snap = AgentSnapshot(
        tick=1,
        speed_mph=0.5,
        station_dist_m=20.0,
        station_fsm="STOPPED",
        doors_telem=True,
        doors_dmi=False,
        doors_open=True,
    )
    trace.write_tick(snap, t_ms=50.0)
    trace.close()
    tick = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[1])
    assert tick["doors_telem"] is True
    assert tick["doors_dmi"] is False
    assert tick["doors_open"] is True


def test_format_investigate_doors():
    snap = AgentSnapshot(
        tick=1,
        doors_telem=True,
        doors_dmi=False,
    )
    line = format_investigate(snap)
    assert "doors=1/0" in line


def test_jsonl_trace_station_fields(tmp_path: Path):
    path = tmp_path / "st.jsonl"
    trace = JsonlTrace(path, session_meta(mode="station", route="test"))
    snap = AgentSnapshot(
        tick=2,
        speed_mph=1.0,
        station_dist_m=22.0,
        station_fsm="DEPARTING",
        p1_target_kind="LIMIT",
    )
    trace.write_tick(snap, t_ms=100.0)
    trace.close()
    tick = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[1])
    assert tick["stn_dist_m"] == 22.0
    assert tick["stn_fsm"] == "DEPARTING"
    assert tick["p1_tgt"] == "LIMIT"


def test_resolve_session_log_path() -> None:
    assert resolve_session_log_path(None, trace_mode="limit", route="x") is None
    default = resolve_session_log_path("", trace_mode="station", route="cross-city")
    assert default is not None
    assert default == default_log_path(mode="station", route="cross-city")
    assert "_station.jsonl" in default.name
    custom = resolve_session_log_path("/tmp/a.jsonl", trace_mode="limit", route="r")
    assert custom == Path("/tmp/a.jsonl")


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
