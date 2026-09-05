"""Tests for L0.6f ammeter helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from tsw6.lab.lab_export import (
    amps_session_verdict,
    extract_amps_snapshot,
    fixture_session_dir,
    load_hud_batch,
    summarize_amps_session,
)

FIXTURE_HUD = Path(__file__).resolve().parent / "fixtures" / "lab" / "hud_batch_323.json"


def test_extract_amps_snapshot_fixture():
    hud = load_hud_batch(FIXTURE_HUD)
    snap = extract_amps_snapshot(hud)
    assert snap["amps"] == 0.0
    assert snap.get("speed_ms") is not None
    assert snap.get("tractive_effort_n") == 0.0


def test_amps_session_verdict_always_zero():
    rows = [{"amps": 0.0}, {"amps": 0.0}]
    assert amps_session_verdict(rows) == "always_zero"


def test_amps_session_verdict_variable():
    rows = [{"amps": 0.0}, {"amps": -120.5}]
    assert amps_session_verdict(rows) == "variable"


def test_summarize_amps_session_fixture_dir():
    session = fixture_session_dir()
    if not (session / "hud_batch.json").is_file():
        pytest.skip("fixture session missing hud_batch.json")
    rows = summarize_amps_session(session)
    assert len(rows) >= 1
    assert rows[0]["amps"] is not None
