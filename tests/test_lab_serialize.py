"""Tests for tsw6.lab.lab_export (serialize.lua mirror + hud_batch parser)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tsw6.lab.lab_export import (
    FIXTURES_LAB,
    compare_hud_to_probe,
    derive_probe_fields_from_hud,
    encode_lua_json,
    encode_lua_value,
    fixture_session_dir,
    load_hud_batch,
)

HUD_FIXTURE = FIXTURES_LAB / "hud_batch_323.json"
PROBE_FIXTURE = FIXTURES_LAB / "probe_line_323.txt"


def test_fixture_hud_batch_loads() -> None:
    hud = load_hud_batch(HUD_FIXTURE)
    assert hud["mode"] == "hud_batch"
    assert hud["vehicle_class"] == "RVM_BCC_WRM_Class323_DMS_A_C"
    assert len(hud.get("lua") or {}) == 16
    assert len(hud.get("http_guess") or {}) == 16
    assert hud.get("errors") == {}


def test_lua_http_guess_keys_align() -> None:
    hud = load_hud_batch(HUD_FIXTURE)
    lua = hud["lua"]
    guess = hud["http_guess"]
    for method in lua:
        suffix = f"Function.{method}"
        assert any(path.endswith(suffix) for path in guess), method


def test_encode_lua_round_trip_scalars() -> None:
    cases = [
        None,
        True,
        False,
        0,
        -3,
        1.25,
        "line\n\t\"x\"",
        [1, 2, 3],
        {"b": 2, "a": 1},
    ]
    for value in cases:
        parsed = json.loads(encode_lua_value(value))
        assert parsed == value


def test_encode_lua_round_trip_hud_fixture() -> None:
    hud = load_hud_batch(HUD_FIXTURE)
    encoded = encode_lua_json(hud["lua"])
    parsed = json.loads(encoded)
    assert set(parsed) == set(hud["lua"])
    for method, block in hud["lua"].items():
        for key, expected in block.items():
            actual = parsed[method][key]
            if isinstance(expected, float):
                assert math.isclose(actual, expected, rel_tol=0, abs_tol=1e-6), method
            else:
                assert actual == expected, method


def test_derive_probe_fields_from_hud_fixture() -> None:
    hud = load_hud_batch(HUD_FIXTURE)
    derived = derive_probe_fields_from_hud(hud)
    assert derived["handle_notch"] == 1
    assert derived["train_brake"] == 1.0
    assert derived["power"] == -3.0
    assert derived["brake_cyl_bar"] == pytest.approx(4.283247188, rel=1e-6)


def test_compare_hud_to_probe_fixture() -> None:
    hud = load_hud_batch(HUD_FIXTURE)
    probe_line = PROBE_FIXTURE.read_text(encoding="utf-8").strip()
    rows = compare_hud_to_probe(hud, probe_line)
    assert rows
    bad = [r for r in rows if r.match in ("mismatch", "missing_lab", "missing_probe")]
    assert not bad, [(r.field, r.match, r.lab_value, r.probe_value) for r in bad]


def test_fixture_session_dir_has_exports() -> None:
    session = fixture_session_dir()
    assert session.is_dir()
    for name in ("hud_batch.json", "controls.json", "session.json", "formation.json"):
        assert (session / name).is_file(), name
