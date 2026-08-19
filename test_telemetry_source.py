"""Tests de tsw_telemetry_source (UE4SS + HTTPAPI)."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from tsw_telemetry_source import TswTelemetrySource, _power_to_handle_notch
from tsw_ue4ss_reader import ProbeSnapshot


def test_power_to_handle_notch_neutral():
    assert _power_to_handle_notch(0) == 4
    assert _power_to_handle_notch(None) == 4
    assert _power_to_handle_notch(1) == 5
    assert _power_to_handle_notch(-1) == 3


def test_get_telemetry_includes_layout_and_vehicle():
    conn = TswTelemetrySource()
    conn.mode = "tsw_api"
    conn._vehicle_name = "BNSF SD40-2 C"
    conn._telem = {
        "speed_mph": 25.0,
        "handle_notch": 4,
        "train_brake_value": 0.2,
        "ind_brake_value": 0.0,
        "dyn_brake_value": 0.0,
        "dyn_brake_active": False,
    }
    with patch.object(conn, "_poll"):
        telem = conn.get_telemetry()
    assert telem["vehicle_name"] == "BNSF SD40-2 C"
    assert telem["control_layout"] == "freight_na"
    assert telem["train_brake_value"] == 0.2
    assert telem["handle_notch"] == 4


def test_get_telemetry_empty_when_searching():
    conn = TswTelemetrySource()
    conn.mode = "searching"
    assert conn.get_telemetry() == {}


def test_probe_prefers_ue4ss_when_fresh(tmp_path: Path):
    getdata = tmp_path / "GetData.txt"
    getdata.write_text(
        "seq=10 speed_ms=5.0 power=1 handle_notch=5 vehicle=Class323\n",
        encoding="utf-8",
    )
    conn = TswTelemetrySource()
    conn._ue4ss_path = getdata
    with patch.object(conn, "_ensure_api_client", return_value=False):
        result = conn.probe()
    assert result == "ue4ss"
    assert conn.mode == "ue4ss"
    assert conn._telem["handle_notch"] == 5
    assert conn._vehicle_name == "Class323"


def test_probe_falls_back_to_api_when_ue4ss_stale(tmp_path: Path):
    getdata = tmp_path / "GetData.txt"
    getdata.write_text("seq=1 speed_ms=1.0 vehicle=x\n", encoding="utf-8")
    old = time.time() - 5.0
    import os

    os.utime(getdata, (old, old))

    conn = TswTelemetrySource()
    conn._ue4ss_path = getdata
    mock_client = MagicMock()
    mock_client.get_json.return_value = {"Meta": {"APIVersion": 2, "GameBuildNumber": 1}}
    mock_reader = MagicMock()
    mock_reader.read.return_value = MagicMock(
        speed_ms=10.0,
        power=0.0,
        train_brake=0.0,
        accel_ms2=0.0,
        power_negative=False,
        source="poll",
        age_ms=12.0,
    )
    with patch("tsw_telemetry_source.client_from_key_file", return_value=mock_client):
        with patch("tsw_telemetry_source.FastControlReader", return_value=mock_reader):
            result = conn.probe()
    assert result == "tsw_api"
    assert conn.mode == "tsw_api"


def test_get_telemetry_from_ue4ss_poll(tmp_path: Path):
    getdata = tmp_path / "GetData.txt"
    getdata.write_text(
        "seq=20 speed_ms=10.0 power=2 handle_notch=6 gradient_pct=1.5 "
        "speed_limit_ms=20 vehicle=RVM_BCC_WRM_Class323_DMS_A_C\n",
        encoding="utf-8",
    )
    conn = TswTelemetrySource()
    conn.mode = "ue4ss"
    conn._ue4ss_path = getdata
    conn._vehicle_name = "RVM_BCC_WRM_Class323_DMS_A_C"
    conn._telem = {"speed_mph": 1.0, "handle_notch": 4}
    with patch.object(conn, "_kick_planning_refresh") as mock_kick:
        telem = conn.get_telemetry()
    mock_kick.assert_called_once()
    assert telem["handle_notch"] == 6
    assert telem["gradient_pct"] == 1.5
    assert telem["control_layout"] == "combined"
    assert telem["telemetry_source"] == "ue4ss"


def test_ue4ss_polls_driver_aid_when_gradient_missing(tmp_path: Path):
    getdata = tmp_path / "GetData.txt"
    getdata.write_text(
        "seq=21 speed_ms=10.0 power=0 handle_notch=4 vehicle=Class323\n",
        encoding="utf-8",
    )
    conn = TswTelemetrySource()
    conn.mode = "ue4ss"
    conn._ue4ss_path = getdata
    planning = {"gradient_pct": 0.8, "next_limit_mph": 20.0, "distance_next_m": 150.0}
    conn._planning_cache = planning
    with patch.object(conn, "_kick_planning_refresh") as mock_kick:
        telem = conn.get_telemetry()
    mock_kick.assert_called_once()
    assert telem["gradient_pct"] == 0.8
    assert telem["next_limit_mph"] == 20.0
    assert telem["distance_next_m"] == 150.0


def test_ue4ss_planning_on_slow_tick_with_probe_gradient(tmp_path: Path):
    getdata = tmp_path / "GetData.txt"
    getdata.write_text(
        "seq=22 speed_ms=10.0 power=0 handle_notch=4 gradient_pct=1.2 vehicle=Class323\n",
        encoding="utf-8",
    )
    conn = TswTelemetrySource()
    conn.mode = "ue4ss"
    conn._ue4ss_path = getdata
    conn._poll_tick = 4  # next tick triggers SLOW_EVERY
    planning = {
        "gradient_pct": 0.1,
        "next_limit_mph": 25.0,
        "distance_next_m": 80.0,
        "stations": [{"name": "Test", "distance_m": 500.0}],
    }
    conn._planning_cache = planning
    with patch.object(conn, "_kick_planning_refresh"):
        telem = conn.get_telemetry()
    assert telem["gradient_pct"] == 1.2  # probe wins
    assert telem["next_limit_mph"] == 25.0
    assert telem["stations"][0]["name"] == "Test"
