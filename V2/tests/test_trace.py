from __future__ import annotations

import _path  # noqa: F401

import json
from pathlib import Path

import pytest

from tsw6v2.loop import AgentSnapshot
from tsw6v2.session_log import SessionRecorder
from tsw6v2.session_report import load_ticks
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
        brake_fill_n=3,
        decel_observe_n=12,
        learn_kind="decel",
        learn_accepted=True,
        learn_reject_reason="accepted",
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
    assert tick["brake_fill_n"] == 3
    assert tick["decel_observe_n"] == 12
    assert tick["learn_kind"] == "decel"
    assert tick["learn_accepted"] is True
    assert tick["learn_reject_reason"] == "accepted"


def test_jsonl_trace_signal_fields(tmp_path: Path) -> None:
    path = tmp_path / "sig.jsonl"
    trace = JsonlTrace(path, session_meta(mode="station", route="test"))
    snap = AgentSnapshot(
        tick=5,
        speed_mph=12.0,
        signal_red=True,
        signal_dist_m=84.2,
        station_fsm="DEPARTING",
    )
    trace.write_tick(snap, t_ms=80.0)
    trace.close()
    tick = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[1])
    assert tick["signal_red"] is True
    assert tick["signal_dist_m"] == 84.2
    line = format_investigate(snap)
    assert "sig=ROJO@84m" in line


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


def test_session_recorder_emits_route_detect(tmp_path: Path) -> None:
    class _Loop:
        def planning_context(self) -> dict[str, object]:
            return {
                "detected_route": "Birmingham Cross-City",
                "service_name": "2R17",
                "schedule_source": "hud_db",
                "hud_timetable_id": 127594,
            }

    path = tmp_path / "sess.jsonl"
    rec = SessionRecorder(path, trace_mode="station", route="cross-city")
    rec.bind_loop(_Loop())
    rec.record(AgentSnapshot(tick=1, seq=1, speed_mph=0.0))
    rec.finish(generate_html=False)
    session, _ = load_ticks(path)
    assert session is not None
    assert session["detected_route"] == "Birmingham Cross-City"
    assert session["service_name"] == "2R17"


def test_session_recorder_active_time_follows_wall_clock_with_repeated_seq(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Límite de fps: ticks con seq repetido no se apilan en el mismo punto del eje X (104709Z)."""
    clock = {"t": 100.0}
    monkeypatch.setattr("tsw6v2.session_log.time.monotonic", lambda: clock["t"])
    path = tmp_path / "sess.jsonl"
    rec = SessionRecorder(path, trace_mode="station", route="x")
    for seq in (10, 10, 11, 11, 12):
        rec.record(AgentSnapshot(tick=1, seq=seq, speed_mph=30.0))
        clock["t"] += 0.05
    for _ in range(10):  # pausa: seq quieto > PROBE_FROZEN_S
        rec.record(AgentSnapshot(tick=1, seq=12, speed_mph=0.0))
        clock["t"] += 0.05
    rec.finish(generate_html=False)
    ticks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()][1:]
    act = [t["active_t_ms"] for t in ticks]
    assert act[:5] == pytest.approx([0.0, 50.0, 100.0, 150.0, 200.0])
    assert act[-1] == act[-2] < 600.0  # en pausa se congela tras PROBE_FROZEN_S (0,3 s)


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


def test_jsonl_trace_concurrent_writes_keep_lines_valid_session_220924Z(tmp_path):
    """Varios hilos escribiendo el mismo JSONL no deben mezclar líneas (220924Z)."""
    import json as _json
    import threading as _threading

    from tsw6v2.trace import JsonlTrace

    path = tmp_path / "concurrent.jsonl"
    trace = JsonlTrace(path, {"mode": "station"})

    def worker(wid: int) -> None:
        for i in range(300):
            trace.write({"type": "tick", "w": wid, "i": i, "pad": "x" * 200})

    threads = [_threading.Thread(target=worker, args=(w,)) for w in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    trace._fp.close()

    rows = [_json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["type"] == "session"
    assert len(rows) == 1 + 6 * 300


def test_jsonl_trace_hud_ocr_fields(tmp_path: Path) -> None:
    path = tmp_path / "ocr.jsonl"
    trace = JsonlTrace(path, session_meta(mode="station", route="test"))
    trace.write_tick(
        AgentSnapshot(tick=1, speed_mph=20.0, hud_ocr_m=446.5, hud_ocr_age_s=0.31, hud_ocr_raw="1.465 ft"),
        t_ms=50.0,
    )
    trace.write_tick(AgentSnapshot(tick=2, speed_mph=20.0), t_ms=100.0)
    trace.close()
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").strip().splitlines()]
    assert lines[1]["hud_ocr_m"] == 446.5 and lines[1]["hud_ocr_age_s"] == 0.31
    assert lines[1]["hud_ocr_raw"] == "1.465 ft"
    assert "hud_ocr_m" not in lines[2]  # sin lector no se ensucia el log
