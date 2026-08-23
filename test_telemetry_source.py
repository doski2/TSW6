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


def test_ue4ss_probe_planning_overrides_http_cache(tmp_path: Path):
    getdata = tmp_path / "GetData.txt"
    getdata.write_text(
        "seq=30 speed_ms=10.0 power=0 handle_notch=4 gradient_pct=1.2 "
        "dist_limit_cm=15000 next_limit_ms=13.41 vehicle=Class323\n",
        encoding="utf-8",
    )
    conn = TswTelemetrySource()
    conn.mode = "ue4ss"
    conn._ue4ss_path = getdata
    conn._planning_cache = {
        "next_limit_mph": 50.0,
        "distance_next_m": 999.0,
        "stations": [{"name": "Test", "distance_m": 500.0}],
    }
    with patch.object(conn, "_kick_planning_refresh"):
        telem = conn.get_telemetry()
    assert telem["next_limit_mph"] == 30.0
    assert telem["distance_next_m"] == 150.0
    assert telem["stations"][0]["name"] == "Test"


def test_planning_distance_dead_reckoning():
    """Distancia al límite baja entre lecturas según velocidad (probe fresco)."""
    conn = TswTelemetrySource()
    conn._sync_planning_snapshot({
        "distance_next_m": 1000.0,
        "speed_limits_ahead": [{"limit_mph": 30.0, "distance_m": 1000.0}],
    })
    conn._planning_dist_last_t = time.monotonic() - 1.0
    parsed = {"speed_mph": 45.0}
    conn._apply_planning_distances(parsed, probe_fresh=True, interpolate=True)
    assert parsed["distance_next_m"] < 980.0
    assert parsed["distance_next_m"] > 960.0


def test_stale_probe_holds_distance():
    """Con probe congelado (pausa), no restar distancia artificialmente."""
    conn = TswTelemetrySource()
    conn._sync_planning_snapshot({
        "distance_next_m": 500.0,
        "speed_limits_ahead": [{"limit_mph": 50.0, "distance_m": 500.0}],
    })
    conn._planning_dist_last_t = time.monotonic() - 1.0
    parsed = {"speed_mph": 60.0}
    conn._apply_planning_distances(parsed, probe_fresh=False)
    assert parsed["distance_next_m"] == 500.0


def test_probe_seq_resync_updates_distance():
    """Nuevo seq del probe resincroniza la distancia."""
    conn = TswTelemetrySource()
    planning_a = {
        "distance_next_m": 800.0,
        "speed_limits_ahead": [{"limit_mph": 50.0, "distance_m": 800.0}],
    }
    conn._apply_planning_distances(
        {"speed_mph": 40.0}, source=planning_a, probe_seq=10, probe_fresh=True)
    planning_b = {
        "distance_next_m": 750.0,
        "speed_limits_ahead": [{"limit_mph": 50.0, "distance_m": 750.0}],
    }
    parsed = {"speed_mph": 40.0}
    conn._apply_planning_distances(
        parsed, source=planning_b, probe_seq=11, probe_fresh=True)
    assert parsed["distance_next_m"] == 750.0


def test_frozen_probe_seq_holds_distance():
    """Mismo seq + velocidad congelada: no odometría (pausa con probe activo)."""
    conn = TswTelemetrySource()
    planning = {
        "distance_next_m": 108.0,
        "speed_limits_ahead": [{"limit_mph": 60.0, "distance_m": 108.0}],
    }
    conn._apply_planning_distances(
        {"speed_mph": 16.7},
        source=planning,
        probe_seq=42,
        probe_fresh=True,
        interpolate=True,
    )
    conn._planning_dist_last_t = time.monotonic() - 2.0
    parsed = {"speed_mph": 16.7}
    conn._apply_planning_distances(
        parsed,
        source=planning,
        probe_seq=42,
        probe_fresh=True,
        interpolate=True,
    )
    assert parsed["distance_next_m"] == 108.0


def test_probe_planning_interpolates_between_game_updates():
    """Entre lecturas del juego (misma dist), odometría con seq nuevo."""
    conn = TswTelemetrySource()
    planning = {
        "distance_next_m": 108.0,
        "speed_limits_ahead": [{"limit_mph": 60.0, "distance_m": 108.0}],
    }
    conn._apply_planning_distances(
        {"speed_mph": 30.0},
        source=planning,
        probe_seq=10,
        probe_fresh=True,
        interpolate=True,
    )
    conn._planning_dist_last_t = time.monotonic() - 1.0
    parsed = {"speed_mph": 30.0}
    conn._apply_planning_distances(
        parsed,
        source=planning,
        probe_seq=11,
        probe_fresh=True,
        interpolate=True,
    )
    assert parsed["distance_next_m"] < 108.0
    assert parsed["distance_next_m"] > 90.0
    held = {"speed_mph": 30.0}
    conn._apply_planning_distances(
        held,
        source=planning,
        probe_seq=11,
        probe_fresh=True,
        interpolate=True,
    )
    assert held["distance_next_m"] == parsed["distance_next_m"]


def test_probe_planning_updates_small_distance_changes(tmp_path: Path):
    """Probe resync cada lectura: cambios <0.5 m deben verse en GUI."""
    getdata = tmp_path / "GetData.txt"
    getdata.write_text(
        "seq=10 speed_ms=21.5 power=0 handle_notch=4 "
        "dist_limit_cm=28800 next_limit_ms=15.65 vehicle=Class323\n",
        encoding="utf-8",
    )
    conn = TswTelemetrySource()
    conn.mode = "ue4ss"
    conn._ue4ss_path = getdata
    with patch.object(conn, "_kick_planning_refresh"):
        telem_a = conn.get_telemetry()
    assert abs(telem_a["distance_next_m"] - 288.0) < 1.0

    getdata.write_text(
        "seq=11 speed_ms=21.5 power=0 handle_notch=4 "
        "dist_limit_cm=28720 next_limit_ms=15.65 vehicle=Class323\n",
        encoding="utf-8",
    )
    with patch.object(conn, "_kick_planning_refresh"):
        telem_b = conn.get_telemetry()
    assert telem_b["distance_next_m"] < telem_a["distance_next_m"]
    assert telem_a["distance_next_m"] - telem_b["distance_next_m"] < 1.5


def test_planning_hold_freezes_distance():
    """Autopilot en pausa: distancias congeladas en caché."""
    conn = TswTelemetrySource()
    conn.set_planning_hold(True)
    planning_a = {
        "distance_next_m": 800.0,
        "speed_limits_ahead": [{"limit_mph": 50.0, "distance_m": 800.0}],
    }
    planning_b = {
        "distance_next_m": 750.0,
        "speed_limits_ahead": [{"limit_mph": 50.0, "distance_m": 750.0}],
    }
    conn._apply_probe_planning(
        {"speed_mph": 60.0}, planning_a, probe_seq=1, probe_fresh=True,
    )
    parsed = {"speed_mph": 60.0}
    conn._apply_probe_planning(
        parsed, planning_b, probe_seq=2, probe_fresh=True,
    )
    assert parsed["distance_next_m"] == 800.0
    assert parsed.get("planning_hold") is True


def test_probe_no_double_count_when_seq_advances():
    """Cada seq nuevo trae dist del juego: no restar otra vez por extrapolación."""
    conn = TswTelemetrySource()
    planning_a = {
        "distance_next_m": 1000.0,
        "speed_limits_ahead": [{"limit_mph": 50.0, "distance_m": 1000.0}],
    }
    planning_b = {
        "distance_next_m": 975.0,
        "speed_limits_ahead": [{"limit_mph": 50.0, "distance_m": 975.0}],
    }
    conn._apply_probe_planning(
        {"speed_mph": 56.0}, planning_a, probe_seq=1, probe_fresh=True,
    )
    parsed = {"speed_mph": 56.0}
    conn._apply_probe_planning(
        parsed, planning_b, probe_seq=2, probe_fresh=True,
    )
    assert abs(parsed["distance_next_m"] - 975.0) < 0.1


def test_probe_holds_distance_when_stopped_and_probe_decreases():
    """Parado: ignorar bajadas espurias del probe (pausa / velocidad residual)."""
    conn = TswTelemetrySource()
    planning_a = {
        "distance_next_m": 500.0,
        "speed_limits_ahead": [{"limit_mph": 50.0, "distance_m": 500.0}],
    }
    planning_b = {
        "distance_next_m": 480.0,
        "speed_limits_ahead": [{"limit_mph": 50.0, "distance_m": 480.0}],
    }
    conn._apply_probe_planning(
        {"speed_mph": 0.0}, planning_a, probe_seq=10, probe_fresh=True,
    )
    parsed = {"speed_mph": 0.0}
    conn._apply_probe_planning(
        parsed, planning_b, probe_seq=11, probe_fresh=True,
    )
    assert parsed["distance_next_m"] == 500.0


def test_probe_same_seq_holds_distance_no_python_odom():
    """API DriverAid @ ~20 Hz: mismo seq → sin restar en Python."""
    conn = TswTelemetrySource()
    planning = {
        "distance_next_m": 200.0,
        "speed_limits_ahead": [{"limit_mph": 35.0, "distance_m": 200.0}],
    }
    conn._apply_probe_planning(
        {"speed_mph": 45.0, "odo_m": 1000.0},
        planning,
        probe_seq=5,
        probe_fresh=True,
    )
    parsed = {"speed_mph": 45.0, "odo_m": 1000.0}
    conn._apply_probe_planning(
        parsed,
        planning,
        probe_seq=5,
        probe_fresh=True,
    )
    assert parsed["distance_next_m"] == 200.0


def test_probe_holds_distance_when_odo_frozen():
    """Odómetro API sin avance: ignorar bajadas de distanceToNextSpeedLimit."""
    conn = TswTelemetrySource()
    planning_a = {
        "distance_next_m": 500.0,
        "speed_limits_ahead": [{"limit_mph": 50.0, "distance_m": 500.0}],
    }
    planning_b = {
        "distance_next_m": 480.0,
        "speed_limits_ahead": [{"limit_mph": 50.0, "distance_m": 480.0}],
    }
    conn._apply_probe_planning(
        {"speed_mph": 56.0, "odo_m": 1000.0},
        planning_a,
        probe_seq=10,
        probe_fresh=True,
    )
    conn._motion_odo_since = time.monotonic() - 1.0
    conn._motion_last_odo_m = 1000.0
    parsed = {"speed_mph": 56.0, "odo_m": 1000.0}
    conn._apply_probe_planning(
        parsed, planning_b, probe_seq=11, probe_fresh=True,
    )
    assert parsed["distance_next_m"] == 500.0


def test_probe_extrap_skipped_when_motion_frozen():
    """Odómetro congelado: ignorar bajada espuria de distanceToNextSpeedLimit."""
    conn = TswTelemetrySource()
    planning = {
        "distance_next_m": 200.0,
        "speed_limits_ahead": [{"limit_mph": 35.0, "distance_m": 200.0}],
    }
    conn._apply_probe_planning(
        {"speed_mph": 45.0, "odo_m": 500.0},
        planning,
        probe_seq=5,
        probe_fresh=True,
    )
    conn._motion_odo_since = time.monotonic() - 1.0
    conn._motion_last_odo_m = 500.0
    parsed = {"speed_mph": 45.0, "odo_m": 500.0}
    planning_lower = {
        "distance_next_m": 180.0,
        "speed_limits_ahead": [{"limit_mph": 35.0, "distance_m": 180.0}],
    }
    conn._apply_probe_planning(
        parsed,
        planning_lower,
        probe_seq=6,
        probe_fresh=True,
    )
    assert parsed.get("probe_motion_frozen") is True
    assert parsed["distance_next_m"] == 200.0


def test_speed_direct_from_probe_no_planning_touch(tmp_path: Path):
    """Velocidad: lectura directa del probe; planning no la altera."""
    getdata = tmp_path / "GetData.txt"
    getdata.write_text(
        "seq=5 speed_ms=22.35 power=0 handle_notch=4 "
        "dist_limit_cm=50000 next_limit_ms=13.41 vehicle=Class323\n",
        encoding="utf-8",
    )
    conn = TswTelemetrySource()
    conn.mode = "ue4ss"
    conn._ue4ss_path = getdata
    conn._planning_dist = {"distance_next_m": 1.0}
    with patch.object(conn, "_kick_planning_refresh"):
        telem = conn.get_telemetry()
    assert abs(telem["speed_mph"] - 50.0) < 0.5
    assert telem.get("probe_seq") == 5


def test_speed_updates_each_probe_read(tmp_path: Path):
    """Cada lectura GetData.txt refresca speed_mph (sin caché intermedio)."""
    getdata = tmp_path / "GetData.txt"
    conn = TswTelemetrySource()
    conn.mode = "ue4ss"
    conn._ue4ss_path = getdata
    with patch.object(conn, "_kick_planning_refresh"):
        getdata.write_text(
            "seq=1 speed_ms=10.0 power=0 handle_notch=4 vehicle=Class323\n",
            encoding="utf-8",
        )
        telem_a = conn.get_telemetry()
        getdata.write_text(
            "seq=2 speed_ms=15.0 power=0 handle_notch=4 vehicle=Class323\n",
            encoding="utf-8",
        )
        telem_b = conn.get_telemetry()
    assert telem_a["speed_mph"] < telem_b["speed_mph"]
    assert abs(telem_a["speed_mph"] - 22.37) < 0.5
    assert abs(telem_b["speed_mph"] - 33.55) < 0.5
