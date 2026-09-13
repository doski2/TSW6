"""FSM mínima dwell — suprime P1 andén."""

from __future__ import annotations

from tsw6v2.constants import NEUTRAL_NOTCH, SERVICE_MAX_BRAKE
from tsw6v2.p1_station_gate import (
    DEPARTING_CLEAR_MPH,
    StationDwellGate,
    doors_effective,
    station_dwell_brake_command,
)


def test_gate_stopped_at_platform_suppresses():
    gate = StationDwellGate()
    gate.update(speed_mph=0.5, station_dist_m=20.0, doors_telem=True)
    assert gate.state == "STOPPED"
    assert gate.suppress_station_brake()


def test_gate_far_approach_without_doors_allows_station_plan():
    """141321Z: stn~68 m parado — no suprimir; P1 puede planificar."""
    gate = StationDwellGate()
    gate.update(speed_mph=0.0, station_dist_m=68.2, doors_telem=False)
    assert not gate.suppress_station_brake(station_dist_m=68.2)


def test_gate_roll_through_platform_without_doors():
    """114202Z / 141321Z: rollo ≥10 mph en andén sin puertas."""
    gate = StationDwellGate()
    gate.update(speed_mph=10.0, station_dist_m=30.0, doors_telem=False)
    assert gate.suppress_station_brake(station_dist_m=30.0, speed_mph=10.0)


def test_gate_coast_approach_in_platform_allows_station_plan():
    """Frenar a ~2 mph en andén sin puertas: sí plan STATION."""
    gate = StationDwellGate()
    gate.update(speed_mph=2.0, station_dist_m=20.0, doors_telem=False, throttle_notch=3)
    assert not gate.suppress_station_brake(station_dist_m=20.0, speed_mph=2.0)


def test_gate_coast_9mph_after_power_not_latched():
    """142034Z: neutro ~9 mph en andén tras tracción — puede frenar."""
    gate = StationDwellGate()
    gate.update(speed_mph=5.0, station_dist_m=50.0, doors_telem=False, throttle_notch=6)
    assert gate.suppress_station_brake(
        station_dist_m=50.0, throttle_notch=6, speed_mph=5.0
    )
    gate.update(speed_mph=9.0, station_dist_m=21.0, doors_telem=False, throttle_notch=4)
    assert not gate.suppress_station_brake(
        station_dist_m=21.0, throttle_notch=4, speed_mph=9.0
    )


def test_gate_station_brake_enabled_after_doors_opened():
    gate = StationDwellGate()
    gate.update(speed_mph=12.0, station_dist_m=30.0, doors_telem=True)
    assert gate._doors_ever_opened
    assert gate.state is None
    assert not gate.suppress_station_brake(station_dist_m=30.0)


def test_doors_effective_priority():
    assert doors_effective(doors_telem=True) is True
    assert doors_effective(doors_telem=False, doors_open=True) is True
    assert doors_effective(doors_telem=False, doors_dmi=None) is False
    assert doors_effective() is None


def test_gate_stopped_coast_without_throttle_stays():
    gate = StationDwellGate()
    gate.update(speed_mph=0.5, station_dist_m=15.0, doors_telem=True)
    assert gate.state == "STOPPED"
    gate.update(speed_mph=12.0, station_dist_m=10.0, throttle_notch=4, doors_telem=True)
    assert gate.state == "STOPPED"


def test_gate_pass_through_throttle_in_platform():
    gate = StationDwellGate()
    gate.update(speed_mph=5.0, station_dist_m=15.0, doors_telem=False, throttle_notch=6)
    assert gate.suppress_station_brake(
        station_dist_m=15.0, throttle_notch=6, speed_mph=5.0
    )


def test_gate_departure_throttle_without_doors_suppresses():
    gate = StationDwellGate()
    gate.update(speed_mph=0.0, station_dist_m=5.2, doors_telem=False, throttle_notch=6)
    assert gate.suppress_station_brake(station_dist_m=5.2, throttle_notch=6)


def test_gate_stopped_exits_at_marker_creep_148mph():
    gate = StationDwellGate()
    gate.update(speed_mph=1.48, station_dist_m=0.6, doors_telem=True)
    assert gate.state == "STOPPED"
    gate.update(speed_mph=1.48, station_dist_m=0.6, doors_telem=True)
    assert gate.state == "DEPARTING"


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
    gate._pass_through = True
    gate._doors_ever_opened = True
    gate.update(speed_mph=DEPARTING_CLEAR_MPH + 1.0, station_dist_m=400.0)
    assert gate.state is None
    assert not gate._pass_through
    assert not gate._doors_ever_opened
    assert not gate.suppress_station_brake(station_dist_m=400.0)


def test_gate_stopped_exits_when_passed_stop_marker():
    gate = StationDwellGate()
    gate.update(speed_mph=0.5, station_dist_m=15.0, doors_telem=True)
    assert gate.state == "STOPPED"
    gate.update(speed_mph=14.0, station_dist_m=0.0, doors_telem=True)
    assert gate.state == "DEPARTING"


def test_gate_stopped_exits_when_far_from_platform():
    gate = StationDwellGate()
    gate.update(speed_mph=0.5, station_dist_m=47.0, doors_telem=True)
    assert gate.state == "STOPPED"
    gate._pass_through = True
    gate.update(speed_mph=56.0, station_dist_m=470.0, doors_telem=True)
    assert gate.state is None
    assert not gate._pass_through
    assert not gate.suppress_station_brake(station_dist_m=470.0)


def test_gate_stopped_exits_when_planning_lost_at_speed():
    gate = StationDwellGate()
    gate.update(speed_mph=0.5, station_dist_m=20.0, doors_telem=True)
    gate.update(speed_mph=15.0, station_dist_m=None, doors_telem=True)
    assert gate.state == "DEPARTING"


def test_station_dwell_brake_command_stopped_and_departing() -> None:
    stopped = station_dwell_brake_command(
        station_fsm="STOPPED",
        speed_mph=0.0,
        lever=4,
        station_dist_m=30.0,
    )
    assert stopped is not None
    assert stopped.kind == "APPLY"
    assert stopped.target_notch == SERVICE_MAX_BRAKE

    release = station_dwell_brake_command(
        station_fsm="DEPARTING",
        speed_mph=5.0,
        lever=3,
        station_dist_m=30.0,
    )
    assert release is not None
    assert release.kind == "RELEASE"
    assert release.target_notch == NEUTRAL_NOTCH

    assert station_dwell_brake_command(
        station_fsm=None,
        speed_mph=0.0,
        lever=4,
        station_dist_m=30.0,
    ) is None
