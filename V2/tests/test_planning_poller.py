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
    src._snap.station_distance_m = 500.0
    src.update(60.0)
    time.sleep(0.05)
    snap = src.update(60.0)
    assert snap.station_distance_m is not None
    assert snap.station_distance_m < 500.0
