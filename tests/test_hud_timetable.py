"""Tests de hud_timetable.py (SQLite en memoria)."""

import sqlite3
from pathlib import Path

import pytest

from tsw6.telemetry.driver_aid_parser import filter_stations_by_stop_names
from tsw6.hud.hud_timetable import (
    HudTimetableStore,
    discover_hud_db,
    is_pass_through_action,
    is_scheduled_stop_action,
)


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE routes (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE timetables (
            id INTEGER PRIMARY KEY,
            service_name TEXT,
            current_service_name TEXT,
            route_id INTEGER
        );
        CREATE TABLE timetable_coordinates (
            timetable_id INTEGER,
            coordinates TEXT
        );
        CREATE TABLE locations (
            id INTEGER PRIMARY KEY,
            route_id INTEGER,
            name TEXT
        );
        CREATE TABLE timetable_actions (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE timetable_entries (
            id INTEGER PRIMARY KEY,
            timetable_id INTEGER,
            sort_order INTEGER,
            time1 TEXT,
            time2 TEXT,
            latitude TEXT,
            longitude TEXT,
            action_id INTEGER,
            location_id INTEGER
        );
        INSERT INTO routes VALUES (1, 'Cross-City Line');
        INSERT INTO timetables VALUES (
            10, '2R17 Cross-City', '2R17', 1);
        INSERT INTO timetable_coordinates VALUES (
            10, '[[-1.83,52.68],[-1.82,52.67]]');
        INSERT INTO timetable_actions VALUES
            (1, 'STOP AT LOCATION'),
            (2, 'GO VIA LOCATION'),
            (3, 'LOAD PASSENGERS');
        INSERT INTO locations VALUES
            (1, 1, 'Four Oaks'),
            (2, 1, 'Blake Street'),
            (3, 1, 'Sutton Coldfield');
        INSERT INTO timetable_entries VALUES
            (100, 10, 0, '10:00', NULL, NULL, NULL, 1, 1),
            (101, 10, 1, '10:05', '10:06', NULL, NULL, 3, 1),
            (102, 10, 2, NULL, NULL, NULL, NULL, 2, 2),
            (103, 10, 3, '10:12', NULL, NULL, NULL, 1, 3);
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def hud_db(tmp_path: Path) -> Path:
    db = tmp_path / "tsw_hud.db"
    _seed_db(db)
    return db


def test_discover_hud_db_explicit(hud_db: Path, tmp_path: Path):
    assert discover_hud_db(hud_db) == hud_db
    assert discover_hud_db(tmp_path / "missing.db") is None


def test_find_active_timetable_with_geo(hud_db: Path):
    store = HudTimetableStore(hud_db)
    match = store.find_active_timetable("2R17", lat=52.676, lng=-1.830)
    assert match is not None
    assert match.id == 10
    assert "Cross-City" in match.route_name


def test_find_active_timetable_rejects_far_geo(hud_db: Path):
    store = HudTimetableStore(hud_db)
    assert store.find_active_timetable("2R17", lat=51.0, lng=-1.0) is None


def test_scheduled_stop_names_skip_via(hud_db: Path):
    store = HudTimetableStore(hud_db)
    names = store.scheduled_stop_names(10)
    assert names == ["Four Oaks", "Sutton Coldfield"]
    assert "Blake Street" not in names


def test_schedule_times_for_station(hud_db: Path):
    from tsw6.hud.hud_timetable import schedule_times_for_station

    store = HudTimetableStore(hud_db)
    entries = store.get_schedule_entries(10)
    arr, dep = schedule_times_for_station(entries, "Four Oaks, anden 1")
    assert arr == "10:00"
    assert dep is None
    arr2, dep2 = schedule_times_for_station(entries, "Sutton Coldfield")
    assert arr2 == "10:12"
    assert dep2 is None


def test_merge_schedule_stations_includes_times(hud_db: Path):
    store = HudTimetableStore(hud_db)
    entries = store.get_schedule_entries(10)
    stops = store.scheduled_stop_names(10)
    merged = store.merge_schedule_stations(
        [{"name": "Four Oaks", "distance_m": 500.0}],
        entries,
        stops,
    )
    assert merged[0].get("arrival") == "10:00"


def test_resolve_service_stops(hud_db: Path):
    store = HudTimetableStore(hud_db)
    resolved = store.resolve_service_stops("2R17", lat=52.676, lng=-1.830)
    assert resolved is not None
    assert resolved["timetable_id"] == 10
    assert len(resolved["stop_names"]) == 2


def test_filter_stations_by_stop_names_no_match_returns_empty():
    stations = [
        {"name": "Lichfield City, anden 2", "distance_m": 0},
        {"name": "Shenstone", "distance_m": 4800},
    ]
    out = filter_stations_by_stop_names(stations, ["Four Oaks", "Sutton Coldfield"])
    assert out == []


def test_merge_schedule_stations_uses_hud_geo_when_track_wrong():
    from tsw6.hud.hud_timetable import HudTimetableStore

    store = HudTimetableStore()
    entries = store.get_schedule_entries(127594)
    stops = store.scheduled_stop_names(127594)
    track = [
        {"name": "Lichfield City, anden 2", "distance_m": 0},
        {"name": "Shenstone", "distance_m": 4800},
    ]
    merged = store.merge_schedule_stations(
        [], entries, stops, lat=52.6799, lng=-1.8256)
    assert merged
    assert "Shenstone" not in {s["name"] for s in merged}
    assert merged[0]["name"] == "Four Oaks"
    assert merged[0]["distance_m"] > 1000
    store.close()


def test_filter_stations_by_stop_names():
    stations = [
        {"name": "Four Oaks, andén 1", "distance_m": 2000},
        {"name": "Blake Street, andén 2", "distance_m": 3500},
    ]
    out = filter_stations_by_stop_names(stations, ["Four Oaks", "Sutton Coldfield"])
    assert len(out) == 1
    assert "Four Oaks" in out[0]["name"]


def test_action_classifiers():
    assert is_pass_through_action("GO VIA LOCATION")
    assert not is_scheduled_stop_action("GO VIA LOCATION")
    assert is_scheduled_stop_action("STOP AT LOCATION")
    assert is_scheduled_stop_action("LOAD PASSENGERS")
