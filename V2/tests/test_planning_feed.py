"""Planning sidecar y dead-reckoning."""

from __future__ import annotations

from tsw6v2.planning_feed import planning_distance_accept, tick_station_distance_m


def test_tick_station_distance_m_advances():
    assert tick_station_distance_m(1000.0, 60.0, 1.0) == 1000.0 - 60.0 * 0.44704


def test_tick_station_distance_m_skips_when_stopped():
    assert tick_station_distance_m(500.0, 0.0, 1.0) == 500.0


def test_planning_distance_rejects_jump_after_platform():
    assert not planning_distance_accept(52.0, 2211.0, 36.8)


def test_planning_distance_accepts_normal_update():
    assert planning_distance_accept(500.0, 480.0, 60.0)
    assert planning_distance_accept(None, 900.0, 0.0)
