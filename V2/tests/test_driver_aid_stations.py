"""Parser TrackData → próxima parada (sin HTTP en vivo)."""

from __future__ import annotations

from pathlib import Path

from tsw6v2.driver_aid_stations import (
    filter_stations_by_service,
    parse_track_data_stations,
    select_next_scheduled_stop,
)


def _sample_track() -> dict:
    return {
        "markers": [
            {
                "markerName": "Four Oaks",
                "markerType": "Platform",
                "distanceToStationCM": 250000,
            },
            {
                "markerName": "Sutton Coldfield",
                "markerType": "Platform",
                "distanceToStationCM": 120000,
            },
            {
                "markerName": "Wrong Way Stop",
                "markerType": "Platform",
                "distanceToStationCM": 50000,
            },
        ]
    }


def test_parse_track_data_stations_sorted():
    stations = parse_track_data_stations(_sample_track())
    assert len(stations) == 3
    assert stations[0]["name"] == "Wrong Way Stop"
    assert stations[-1]["name"] == "Four Oaks"


def test_filter_by_timetable(tmp_path: Path):
    timetable = {"2R17": ["Four Oaks", "Sutton Coldfield"]}
    path = tmp_path / "timetable.json"
    import json

    path.write_text(json.dumps(timetable), encoding="utf-8")
    stations = parse_track_data_stations(_sample_track())
    from tsw6v2.driver_aid_stations import load_service_timetable

    loaded = load_service_timetable(path)
    filtered = filter_stations_by_service(stations, loaded, "2R17")
    names = {s["name"] for s in filtered}
    assert "Wrong Way Stop" not in names
    assert "Four Oaks" in names


def test_select_next_stop_ahead():
    stations = parse_track_data_stations(_sample_track())
    nxt = select_next_scheduled_stop(stations, min_distance_m=100.0)
    assert nxt is not None
    assert nxt["name"] == "Wrong Way Stop"
