from __future__ import annotations

import _path  # noqa: F401

import pytest

from tsw6v2.loop import AgentLoop
from tsw6v2.p1_mode import GUI_P1_MODES, apply_p1_mode, resolve_p1_mode, session_trace_mode


def test_resolve_p1_mode_limit_brake_shortcut():
    assert resolve_p1_mode(mode=None, limit_brake=True) == "limit"
    assert resolve_p1_mode(mode="signal", limit_brake=False) == "signal"


def test_resolve_p1_mode_unknown():
    with pytest.raises(ValueError):
        resolve_p1_mode(mode="freight", limit_brake=False)


def test_apply_p1_mode_limit():
    loop = AgentLoop()
    warnings = apply_p1_mode(loop, "limit")
    assert loop.limit_brake_enabled
    assert warnings == []


def test_gui_p1_modes_product():
    assert GUI_P1_MODES == ("off", "p1")


def test_apply_p1_mode_p1_enables_limit_and_station():
    loop = AgentLoop()
    warnings = apply_p1_mode(loop, "p1")
    assert loop.limit_brake_enabled
    assert loop.station_brake_enabled
    assert len(warnings) == 1
    assert "P1 estación" in warnings[0]
    assert "señal" not in warnings[0].lower()


def test_session_trace_mode_p1_alias_station():
    assert session_trace_mode("p1") == "station"
    assert session_trace_mode("limit") == "limit"
    assert session_trace_mode("console") == "probe-only"


def test_apply_p1_mode_station_enables_limit_and_station():
    loop = AgentLoop()
    warnings = apply_p1_mode(loop, "station")
    assert loop.limit_brake_enabled
    assert loop.station_brake_enabled
    assert len(warnings) == 1
    assert "P1 estación" in warnings[0]


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
