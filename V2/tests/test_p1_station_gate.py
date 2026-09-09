"""FSM mínima dwell — suprime P1 andén."""

from __future__ import annotations

from tsw6v2.p1_station_gate import (
    DEPARTING_CLEAR_MPH,
    StationDwellGate,
)


def test_gate_stopped_at_platform_suppresses():
    gate = StationDwellGate()
    gate.update(speed_mph=0.5, station_dist_m=20.0)
    assert gate.state == "STOPPED"
    assert gate.suppress_station_brake()


def test_gate_departing_after_doors_close():
    gate = StationDwellGate()
    gate.update(speed_mph=0.5, station_dist_m=15.0, doors_telem=True)
    assert gate.state == "STOPPED"
    gate.update(speed_mph=0.5, station_dist_m=15.0, doors_telem=False)
    assert gate.state == "DEPARTING"
    assert gate.suppress_station_brake()


def test_gate_clears_after_departure_speed():
    gate = StationDwellGate()
    gate.state = "DEPARTING"
    gate._departing_at = 0.0
    gate.update(speed_mph=DEPARTING_CLEAR_MPH + 1.0, station_dist_m=400.0)
    assert gate.state is None
    assert not gate.suppress_station_brake()
