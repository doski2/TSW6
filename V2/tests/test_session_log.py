from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import _path  # noqa: F401

from tsw6v2.loop import AgentLoop, AgentSnapshot
from tsw6v2.learner import LearnerProfile
from tsw6v2.loop import AgentLoop
from tsw6v2.session_log import (
    SessionRecorder,
    make_session_recorder,
    session_profile_note,
)


def test_session_recorder_writes_jsonl_and_html(tmp_path: Path) -> None:
    log = tmp_path / "sess.jsonl"
    rec = SessionRecorder(log, trace_mode="station", route="test")
    snap = AgentSnapshot(
        tick=1,
        speed_mph=50.0,
        lever_notch=4,
        limit_mph=55.0,
        limit_dist_m=200.0,
        station_dist_m=800.0,
        p1_target_kind="SPEED_LIMIT",
        p1_cmd="APPLY",
        p1_phase="B1",
        p1_reason="plan",
        p1_apply_now=True,
        p1_dist_start_m=10.0,
    )
    for i in range(20):
        snap.tick = i + 1
        rec.record(snap)
    with patch("tsw6v2.session_log.os.startfile"):
        result = rec.finish(open_html=False, force_html=True)
    assert result.html_path is not None
    assert result.html_path.exists()
    assert log.exists()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["type"] == "session"
    assert "cartel" in result.html_path.read_text(encoding="utf-8")


def test_session_recorder_empty_finish(tmp_path: Path) -> None:
    rec = SessionRecorder(tmp_path / "empty.jsonl", trace_mode="station", route="x")
    result = rec.finish()
    assert "sin ticks" in result.message or result.summary.get("error")


def test_session_profile_note_explicit_and_auto(tmp_path: Path) -> None:
    profile = tmp_path / "p.json"
    profile.write_text("{}", encoding="utf-8")
    loop = AgentLoop(learner=LearnerProfile.from_json(profile))
    assert session_profile_note(loop, profile) == str(profile)
    loop2 = AgentLoop(auto_profile=False)
    loop2._profile_path = profile  # noqa: SLF001 — test auto-carga
    assert session_profile_note(loop2, None) == str(profile)


def test_make_session_recorder_resolves_profile(tmp_path: Path) -> None:
    profile = tmp_path / "learner.json"
    profile.write_text("{}", encoding="utf-8")
    loop = AgentLoop(learner=LearnerProfile.from_json(profile))
    log = tmp_path / "mk.jsonl"
    rec = make_session_recorder(
        log,
        loop,
        trace_mode="limit",
        route="test",
        profile_path=profile,
    )
    assert rec.profile == str(profile)


def test_session_recorder_profile_in_jsonl_header(tmp_path: Path) -> None:
    log = tmp_path / "prof.jsonl"
    rec = SessionRecorder(
        log,
        trace_mode="station",
        route="test",
        profile="/logs/profiles/Class_323.json",
    )
    rec.record(AgentSnapshot(tick=1, speed_mph=10.0, lever_notch=4))
    header = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert header["profile"] == "/logs/profiles/Class_323.json"


def test_session_recorder_finish_without_html(tmp_path: Path) -> None:
    log = tmp_path / "no_html.jsonl"
    rec = SessionRecorder(log, trace_mode="limit", route="test")
    snap = AgentSnapshot(tick=1, speed_mph=40.0, lever_notch=4)
    rec.record(snap)
    result = rec.finish(generate_html=False)
    assert result.html_path is None
    assert log.exists()
    assert "JSONL" in result.message
