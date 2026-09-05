from __future__ import annotations

import _path  # noqa: F401

import pytest

from tsw6v2.loop import AgentLoop
from tsw6v2.p1_mode import apply_p1_mode, resolve_p1_mode


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


def test_apply_p1_mode_station_warns():
    loop = AgentLoop()
    warnings = apply_p1_mode(loop, "station")
    assert not loop.limit_brake_enabled
    assert any("estación" in w for w in warnings)


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
