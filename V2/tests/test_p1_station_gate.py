"""FSM mínima dwell — suprime P1 andén."""

from __future__ import annotations

from tsw6v2.constants import NEUTRAL_NOTCH, SERVICE_MAX_BRAKE
from tsw6v2.p1_station_gate import (
    DEPARTING_CLEAR_MPH,
    StationDwellGate,
    doors_effective,
    should_skip_p1_release,
    station_departure_active,
    station_departure_suppresses_limit_brake,
    station_dwell_brake_command,
)
from tsw6v2.station_plan import is_origin_station_departure


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


def test_gate_brake_approach_not_roll_through_session_213920():
    """213920Z tick 27924: B2 @55 m y ~16 mph no es passthrough (sí plan STATION)."""
    gate = StationDwellGate()
    gate.update(speed_mph=15.9, station_dist_m=54.8, doors_telem=False, throttle_notch=2)
    assert not gate.suppress_station_brake(
        station_dist_m=54.8,
        throttle_notch=2,
        speed_mph=15.9,
    )


def test_gate_approach_after_signal_not_roll_through_session_155851():
    """155851Z Longbridge: neutro ~13 mph en stn<55 m tras señal — sí plan STATION."""
    gate = StationDwellGate()
    gate.update(speed_mph=13.0, station_dist_m=54.9, doors_telem=False, throttle_notch=4)
    assert not gate.suppress_station_brake(
        station_dist_m=54.9,
        throttle_notch=4,
        speed_mph=13.0,
    )


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


def test_origin_station_departure_rejects_mid_route_approach_session_211032() -> None:
    """211032Z: stn≈559 m @ 20 mph no es salida de origen (umbral 15 km)."""
    assert not is_origin_station_departure(
        speed_mph=20.21,
        station_distance_m=559.3,
        throttle_notch=6,
    )
    gate = StationDwellGate()
    gate.update(
        speed_mph=20.21,
        station_dist_m=559.3,
        doors_telem=False,
        throttle_notch=4,
    )
    assert gate.state is None
    assert not gate.suppress_station_brake(
        station_dist_m=559.3,
        speed_mph=20.21,
        throttle_notch=4,
    )


def test_gate_departing_allows_station_brake_on_mid_route_approach() -> None:
    gate = StationDwellGate()
    gate.state = "DEPARTING"
    gate._departing_at = 0.0
    assert not gate.suppress_station_brake(
        station_dist_m=400.0,
        speed_mph=20.0,
    )
    assert gate.suppress_station_brake(
        station_dist_m=30.0,
        speed_mph=15.0,
    )


def test_origin_station_departure_detected_session_214610() -> None:
    """Lichfield TV: next_stop a 24 km + tracción → DEPARTING sin FSM STOPPED."""
    assert is_origin_station_departure(
        speed_mph=0.0,
        station_distance_m=24182.5,
        throttle_notch=2,
    )
    gate = StationDwellGate()
    gate.update(
        speed_mph=0.0,
        station_dist_m=24182.5,
        doors_telem=False,
        throttle_notch=6,
    )
    assert gate.state == "DEPARTING"
    assert gate.suppress_station_brake(station_dist_m=24182.5, throttle_notch=6)


def test_station_departure_suppresses_limit_only_in_creep() -> None:
    assert station_departure_suppresses_limit_brake(
        speed_mph=10.0,
        station_dist_m=24025.9,
        combined_lever=5,
        station_fsm="DEPARTING",
    )
    assert station_departure_suppresses_limit_brake(
        speed_mph=10.25,
        station_dist_m=24025.9,
        combined_lever=5,
        station_fsm="DEPARTING",
    )
    assert not station_departure_suppresses_limit_brake(
        speed_mph=12.5,
        station_dist_m=24141.8,
        combined_lever=4,
        station_fsm="DEPARTING",
    )


def test_station_departure_active_origin_and_clear_speed() -> None:
    assert station_departure_active(
        speed_mph=10.25,
        station_dist_m=24025.9,
        combined_lever=5,
        station_fsm="DEPARTING",
    )
    assert not station_departure_active(
        speed_mph=30.0,
        station_dist_m=24025.9,
        combined_lever=5,
        station_fsm="DEPARTING",
    )


def test_skip_p1_release_final_approach_session_213633() -> None:
    """Aproximación final: bloquear RELEASE heredado cartel/señal."""
    assert should_skip_p1_release(
        speed_mph=17.0,
        station_dist_m=62.0,
        combined_lever=2,
        station_fsm=None,
    )
    assert not should_skip_p1_release(
        speed_mph=10.0,
        station_dist_m=0.5,
        combined_lever=6,
        station_fsm=None,
    )


def test_mid_route_service_platform_session_191546() -> None:
    """Five Ways 2R99: parado ~1.5 km al next stop; salida con tracción tras cerrar puertas."""
    stn = 1523.1
    assert should_skip_p1_release(
        speed_mph=0.0,
        station_dist_m=stn,
        combined_lever=NEUTRAL_NOTCH,
        station_fsm=None,
        brake_cyl_bar=1.0,
    )
    assert should_skip_p1_release(
        speed_mph=0.0,
        station_dist_m=stn,
        combined_lever=NEUTRAL_NOTCH,
        station_fsm=None,
        brake_cyl_bar=5.16,
    )
    assert not should_skip_p1_release(
        speed_mph=0.0,
        station_dist_m=stn,
        combined_lever=2,
        station_fsm=None,
        brake_cyl_bar=5.16,
    )
    assert should_skip_p1_release(
        speed_mph=0.0,
        station_dist_m=stn,
        combined_lever=3,
        station_fsm=None,
        brake_cyl_bar=5.16,
        platform_bleed_episode=True,
    )
    assert not station_departure_active(
        speed_mph=0.0,
        station_dist_m=stn,
        combined_lever=NEUTRAL_NOTCH,
        station_fsm=None,
    )
    assert station_departure_active(
        speed_mph=0.0,
        station_dist_m=stn,
        combined_lever=5,
        station_fsm=None,
    )
    assert should_skip_p1_release(
        speed_mph=0.0,
        station_dist_m=stn,
        combined_lever=5,
        station_fsm=None,
    )
    assert station_departure_suppresses_limit_brake(
        speed_mph=8.0,
        station_dist_m=stn,
        combined_lever=5,
        station_fsm=None,
    )


def test_departing_fsm_creep_after_marker_mid_route() -> None:
    assert station_departure_active(
        speed_mph=10.0,
        station_dist_m=1523.0,
        combined_lever=5,
        station_fsm="DEPARTING",
    )


def test_skip_p1_release_during_departure() -> None:
    """Salida: sin RELEASE heredado cartel/señal; solo ``_attempt_departing_brake_release``."""
    assert should_skip_p1_release(
        speed_mph=0.0,
        station_dist_m=24182.5,
        combined_lever=3,
        station_fsm="DEPARTING",
    )
    assert should_skip_p1_release(
        speed_mph=0.0,
        station_dist_m=24182.5,
        combined_lever=6,
        station_fsm="DEPARTING",
    )
    assert not should_skip_p1_release(
        speed_mph=0.0,
        station_dist_m=24182.5,
        combined_lever=3,
        station_fsm=None,
        brake_cyl_bar=5.0,
    )


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

    assert station_dwell_brake_command(
        station_fsm="DEPARTING",
        speed_mph=5.0,
        lever=3,
        station_dist_m=30.0,
    ) is None

    assert station_dwell_brake_command(
        station_fsm=None,
        speed_mph=0.0,
        lever=4,
        station_dist_m=30.0,
    ) is None
