"""Integración V2 planning ↔ tsw_hud.db."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tsw6v2.driver_aid_stations import parse_track_data_stations
from tsw6v2.hud_schedule import (
    apply_station_schedule,
    pick_next_scheduled_stop,
    service_name_variants,
)


def _track() -> dict:
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


def test_service_name_variants_includes_u_o_alias():
    assert "5O02" in service_name_variants("5U02")


def test_apply_station_schedule_hud_db():
    stations = parse_track_data_stations(_track())
    hud_match = {
        "timetable_id": 127605,
        "stop_names": ["Four Oaks"],
        "entries": [],
        "route_name": "Birmingham Cross-City",
    }
    with patch("tsw6v2.hud_schedule.resolve_hud_service_stops", return_value=hud_match):
        with patch("tsw6v2.hud_schedule._hud_store") as mock_store:
            mock_store.return_value = MagicMock(
                merge_schedule_stations=lambda *a, **k: [
                    {"name": "Four Oaks", "distance_m": 2500.0, "scheduled": True}
                ]
            )
            filtered, src, match = apply_station_schedule(
                stations, "5U02 Birmingham New Street to Four Oaks", lat=52.48, lng=-1.90
            )
    assert src == "hud_db"
    assert match is hud_match
    assert len(filtered) == 1
    assert filtered[0]["name"] == "Four Oaks"


def test_apply_station_schedule_falls_back_to_timetable_json():
    stations = parse_track_data_stations(_track())
    timetable = {"2R17": ["Four Oaks", "Sutton Coldfield"]}
    with patch("tsw6v2.hud_schedule.resolve_hud_service_stops", return_value=None):
        filtered, src, _ = apply_station_schedule(
            stations, "2R17", timetable=timetable
        )
    assert src == "timetable_json"
    names = {s["name"] for s in filtered}
    assert "Wrong Way Stop" not in names


def test_pick_next_excludes_served_bases_session_215036():
    stations = [
        {"name": "Five Ways", "distance_m": 1200.0, "scheduled": True},
        {"name": "University, andén 2", "distance_m": 1700.0, "scheduled": True},
    ]
    nxt = pick_next_scheduled_stop(stations, exclude_bases={"five ways"})
    assert nxt is not None
    assert "university" in nxt["name"].lower()


def test_pick_next_uses_hud_order_when_track_empty():
    hud_match = {"stop_names": ["Four Oaks", "Sutton Coldfield"]}
    nxt = pick_next_scheduled_stop([], hud_match=hud_match)
    assert nxt is not None
    assert nxt["name"] == "Four Oaks"
