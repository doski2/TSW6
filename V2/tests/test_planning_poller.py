"""StationPlanning: archivo y dead-reckoning."""

from __future__ import annotations

import time

from tsw6v2.planning_feed import format_planning_line
from tsw6v2.planning_poller import StationPlanning


def test_station_planning_reads_file(tmp_path):
    path = tmp_path / "Planning.txt"
    path.write_text(
        format_planning_line(station_distance_m=900.0, station_name="Sutton") + "\n",
        encoding="utf-8",
    )
    src = StationPlanning(path=path, http_enabled=False)
    assert src.source == "file"
    src.update(60.0)
    time.sleep(0.05)
    snap = src.update(60.0)
    assert snap.station_distance_m is not None
    assert snap.station_distance_m < 900.0


def test_station_planning_rejects_http_jump_to_next_stop(monkeypatch):
    monkeypatch.setattr(
        "tsw6v2.planning_poller.poll_station_planning",
        lambda: {"next_stop": {"distance_m": 2211.0, "name": "Next"}},
    )
    src = StationPlanning(http_enabled=False)
    src._http_ok = True
    src._source = "http"
    src._snap.station_distance_m = 52.0
    src._last_speed_mph = 36.8
    src._poll_once()
    assert src._snap.station_distance_m == 52.0


def test_station_planning_http_dead_reckoning():
    src = StationPlanning(http_enabled=False)
    src._http_ok = True
    src._source = "http"
    src._startup_invalidate_pending = False
    src._last_probe_seq = 100
    src._snap.station_distance_m = 500.0
    snap = src.update(60.0, probe_seq=103)
    assert snap.station_distance_m is not None
    assert snap.station_distance_m < 500.0


def test_station_planning_skips_dead_reckoning_when_probe_seq_frozen():
    src = StationPlanning(http_enabled=False)
    src._http_ok = True
    src._source = "http"
    src._startup_invalidate_pending = False
    src._last_probe_seq = 100
    src._snap.station_distance_m = 500.0
    snap = src.update(60.0, probe_seq=100)
    assert snap.station_distance_m == 500.0


def test_station_planning_rejects_http_regression(monkeypatch):
    monkeypatch.setattr(
        "tsw6v2.planning_poller.poll_station_planning",
        lambda: {"next_stop": {"distance_m": 235.4, "name": "Stn"}},
    )
    src = StationPlanning(http_enabled=False)
    src._http_ok = True
    src._snap.station_distance_m = 230.7
    src._last_speed_mph = 23.0
    src._poll_once()
    assert src._snap.station_distance_m == 230.7


def test_station_planning_resets_on_first_probe_seq(monkeypatch):
    monkeypatch.setattr(
        "tsw6v2.planning_poller.poll_station_planning",
        lambda: {
            "next_stop": {"distance_m": 900.0, "name": "Sutton"},
            "service_name": "2R17",
            "hud_route_name": "Birmingham Cross-City",
            "hud_timetable_id": 127594,
            "schedule_source": "hud_db",
        },
    )
    src = StationPlanning(http_enabled=False)
    src._http_ok = True
    src._snap.station_distance_m = 50.0
    src.update(0.0, probe_seq=501522)
    assert src._snap.station_distance_m == 900.0


def test_station_planning_resets_on_service_change(monkeypatch):
    calls = {"n": 0}

    def fake_poll():
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "next_stop": {"distance_m": 24000.0, "name": "Far"},
                "service_name": "2R17",
                "hud_route_name": "Birmingham Cross-City",
                "hud_timetable_id": 127594,
            }
        return {
            "next_stop": {"distance_m": 500.0, "name": "Near"},
            "service_name": "2R18",
            "hud_route_name": "Birmingham Cross-City",
            "hud_timetable_id": 127595,
        }

    monkeypatch.setattr("tsw6v2.planning_poller.poll_station_planning", fake_poll)
    src = StationPlanning(http_enabled=False)
    src._http_ok = True
    src._poll_once()
    assert src._snap.station_distance_m == 24000.0
    src._poll_once()
    assert src._snap.station_distance_m == 500.0


def test_station_planning_sets_route_when_distance_rejected(monkeypatch):
    monkeypatch.setattr(
        "tsw6v2.planning_poller.poll_station_planning",
        lambda: {
            "next_stop": {"distance_m": 120.8, "name": "Wrong"},
            "service_name": "2R17",
            "hud_route_name": "Birmingham Cross-City",
            "hud_timetable_id": 127594,
            "schedule_source": "hud_db",
        },
    )
    src = StationPlanning(http_enabled=False)
    src._http_ok = True
    src._snap.station_distance_m = 22184.0
    src._last_speed_mph = 45.0
    src._poll_once()
    assert src._snap.station_distance_m == 22184.0
    assert src.detected_route == "Birmingham Cross-City"
    assert src.context_snapshot()["service_name"] == "2R17"


def test_station_planning_rejects_large_yoyo_at_speed(monkeypatch):
    src = StationPlanning(http_enabled=False)
    src._http_ok = True
    src._last_speed_mph = 45.0

    monkeypatch.setattr(
        "tsw6v2.planning_poller.poll_station_planning",
        lambda: {"next_stop": {"distance_m": 120.8, "name": "Wrong"}},
    )
    src._snap.station_distance_m = 22184.0
    src._poll_once()
    assert src._snap.station_distance_m == 22184.0

    monkeypatch.setattr(
        "tsw6v2.planning_poller.poll_station_planning",
        lambda: {"next_stop": {"distance_m": 24000.0, "name": "Far"}},
    )
    src._snap.station_distance_m = 2000.0
    src._poll_once()
    assert src._snap.station_distance_m == 2000.0


def test_station_planning_resets_on_probe_seq_discontinuity(monkeypatch):
    monkeypatch.setattr(
        "tsw6v2.planning_poller.poll_station_planning",
        lambda: {"next_stop": {"distance_m": 1200.0, "name": "Far"}},
    )
    src = StationPlanning(http_enabled=False)
    src._http_ok = True
    src._snap.station_distance_m = 235.0
    src._last_probe_seq = 5000
    src.update(60.0, probe_seq=120)
    assert src._snap.station_distance_m == 1200.0
