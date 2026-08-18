"""Tests get_telemetry enriquecido con layout (Fase 1)."""

from unittest.mock import patch

from tsw_connection import TswConnection


def test_get_telemetry_includes_layout_and_vehicle():
    conn = TswConnection()
    conn.mode = "companion"
    conn._vehicle_name = "BNSF SD40-2 C"
    conn._telem = {
        "speed_mph": 25.0,
        "handle_notch": 4,
        "train_brake_value": 0.2,
        "ind_brake_value": 0.0,
        "dyn_brake_value": 0.0,
        "dyn_brake_active": False,
    }
    telem = conn.get_telemetry()
    assert telem["vehicle_name"] == "BNSF SD40-2 C"
    assert telem["control_layout"] == "freight_na"
    assert telem["train_brake_value"] == 0.2
    assert telem["handle_notch"] == 4


def test_get_telemetry_empty_when_searching():
    conn = TswConnection()
    conn.mode = "searching"
    assert conn.get_telemetry() == {}
