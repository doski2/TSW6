"""Parser TrackData → próxima parada (sin HTTP en vivo)."""

from __future__ import annotations

from tsw6v2.track_stations import (
    filter_stations_by_stop_names,
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


def test_filter_by_hud_stop_names():
    stations = parse_track_data_stations(_sample_track())
    filtered = filter_stations_by_stop_names(stations, ["Four Oaks", "Sutton Coldfield"])
    names = {s["name"] for s in filtered}
    assert "Wrong Way Stop" not in names
    assert "Four Oaks" in names


def test_select_next_stop_ahead():
    stations = parse_track_data_stations(_sample_track())
    nxt = select_next_scheduled_stop(stations, min_distance_m=100.0)
    assert nxt is not None
    assert nxt["name"] == "Wrong Way Stop"
