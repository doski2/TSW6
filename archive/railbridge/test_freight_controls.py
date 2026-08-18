"""Tests de parseo de controles NA freight (brake_gauges anidado)."""

from tsw_connection import TswConnection


def test_flatten_brake_gauges_nested():
    data = {
        "controls": {
            "throttle_notch": {"value": 5},
            "brake_gauges": {
                "automatic": {"value": 0.42, "phase": "SERVICE"},
                "independent": {"value": 0.15},
                "dynamic": {"value": 3},
            },
            "automatic_brake_status": {"value": "LAP"},
        }
    }
    flat = TswConnection._controls_from_delta(data)
    assert flat["throttle_notch"] == 5
    assert flat["brake_gauges.automatic"] == 0.42
    assert flat["brake_gauges.automatic.phase"] == "SERVICE"
    assert flat["brake_gauges.dynamic"] == 3
    assert flat["automatic_brake_status"] == "LAP"

    parsed: dict = {}
    conn = TswConnection()
    conn._apply_controls_delta(data, parsed)
    assert parsed["handle_notch"] == 5
    assert parsed["train_brake_value"] == 0.42
    assert parsed["train_brake_phase"] == "LAP"
    assert parsed["ind_brake_value"] == 0.15
    assert parsed["dyn_brake_notch"] == 3


def test_railbridge_v3_handle_position():
    """Estructura real SD40-2 sesión 2026-06-13 (RailBridge v3 nested handles)."""
    data = {
        "controls": {
            "train_brake_handle": {
                "handle_position": {"value": 0.6992},
                "is_active": {"value": True},
            },
            "locomotive_brake_handle": {
                "handle_position": {"value": 0.9556},
            },
            "electric_brake_handle": {
                "handle_position": {"value": 0.4186},
                "is_active": {"value": True},
            },
        }
    }
    parsed: dict = {}
    TswConnection()._apply_controls_delta(data, parsed)
    assert parsed["train_brake_value"] == 0.6992
    assert parsed["ind_brake_value"] == 0.9556
    assert parsed["dyn_brake_value"] == 0.4186
    assert parsed["dyn_brake_active"] is True


def test_flat_handles_still_work():
    data = {
        "controls": {
            "train_brake_handle": {"value": 0.75},
            "electric_brake_handle": {"value": 2},
        }
    }
    parsed: dict = {}
    TswConnection()._apply_controls_delta(data, parsed)
    assert parsed["train_brake_value"] == 0.75
    assert parsed["dyn_brake_notch"] == 2
