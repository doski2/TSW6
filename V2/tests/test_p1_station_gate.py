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


def test_gate_stopped_at_spawn_distance_47m():
    """Spawn cross-city: stn~47 m al arrancar escenario."""
    gate = StationDwellGate()
    gate.update(speed_mph=0.0, station_dist_m=47.2)
    assert gate.state == "STOPPED"
    assert gate.suppress_station_brake()


def test_gate_stopped_does_not_depart_on_speed_without_doors():
    gate = StationDwellGate()
    gate.update(speed_mph=0.5, station_dist_m=15.0)
    assert gate.state == "STOPPED"
    gate.update(speed_mph=12.0, station_dist_m=10.0)
    assert gate.state == "STOPPED"


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


def test_gate_stopped_exits_when_passed_stop_marker():
    gate = StationDwellGate()
    gate.update(speed_mph=0.5, station_dist_m=15.0)
    assert gate.state == "STOPPED"
    gate.update(speed_mph=14.0, station_dist_m=0.0)
    assert gate.state == "DEPARTING"


def test_gate_stopped_exits_when_far_from_platform():
    gate = StationDwellGate()
    gate.update(speed_mph=0.5, station_dist_m=47.0)
    assert gate.state == "STOPPED"
    gate.update(speed_mph=56.0, station_dist_m=470.0)
    assert gate.state is None
    assert not gate.suppress_station_brake()


def test_gate_stopped_exits_when_planning_lost_at_speed():
    gate = StationDwellGate()
    gate.update(speed_mph=0.5, station_dist_m=20.0)
    gate.update(speed_mph=15.0, station_dist_m=None)
    assert gate.state == "DEPARTING"
