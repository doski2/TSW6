"""Tests de driver_aid_parser."""

from tsw6.telemetry.driver_aid_parser import (
    build_speed_limits_queue,
    filter_stations_by_service,
    parse_driver_aid_planning,
    parse_gradient_pct,
    parse_track_data_stations,
    resolve_display_next_stop,
    select_next_scheduled_stop,
    station_base_name,
)


def test_parse_gradient_pct():
    assert parse_gradient_pct({"gradient": 1.5}) == 1.5
    assert parse_gradient_pct({"gradient": {"value": -0.8}}) == -0.8


def test_parse_driver_aid_next_limit():
    data = {
        "distanceToNextSpeedLimit": 20000.0,  # 200 m
        "nextSpeedLimit": {"value": 8.94},    # ~20 mph
        "nextSpeedLimits": [
            {"distanceToNextSpeedLimit": 15000.0, "value": {"value": 13.41}},
        ],
    }
    out = parse_driver_aid_planning(data)
    assert out["distance_next_m"] == 150.0
    assert abs(out["next_limit_mph"] - 30.0) < 1.0
    assert len(out["speed_limits_ahead"]) == 2
    assert out["speed_limits_ahead"][0]["distance_m"] == 150.0
    assert abs(out["next_limit_2_mph"] - 20.0) < 1.0
    assert out["distance_next_2_m"] == 200.0


def test_build_speed_limits_queue_skips_zero_distance():
    """En cartel (dist=0) usa nextSpeedLimits[], no el par primario."""
    data = {
        "distanceToNextSpeedLimit": 0.0,
        "nextSpeedLimit": {"value": 26.82},  # 60 mph — límite actual
        "nextSpeedLimits": [
            {"distanceToNextSpeedLimit": 392167.0, "value": {"value": 22.35}},  # 50 mph
        ],
    }
    limits = build_speed_limits_queue(data)
    assert len(limits) == 1
    assert limits[0]["distance_m"] > 3900.0
    assert abs(limits[0]["limit_mph"] - 50.0) < 1.0


def test_build_speed_limits_queue_dedupes_near_duplicates():
    data = {
        "distanceToNextSpeedLimit": 50000.0,
        "nextSpeedLimit": {"value": 20.12},
        "nextSpeedLimits": [
            {"distanceToNextSpeedLimit": 50200.0, "value": {"value": 20.12}},
            {"distanceToNextSpeedLimit": 120000.0, "value": {"value": 11.18}},
        ],
    }
    limits = build_speed_limits_queue(data)
    assert len(limits) == 2
    assert limits[0]["distance_m"] == 500.0
    assert limits[1]["distance_m"] == 1200.0


def test_build_speed_limits_queue_collapses_same_mph_at_distances():
    """DriverAid repite el mismo cartel a distancias distintas (ruido GUI)."""
    mph_45_ms = 20.12  # ~45 mph
    data = {
        "distanceToNextSpeedLimit": 29700.0,
        "nextSpeedLimit": {"value": mph_45_ms},
        "nextSpeedLimits": [
            {"distanceToNextSpeedLimit": 31600.0, "value": {"value": mph_45_ms}},
            {"distanceToNextSpeedLimit": 33500.0, "value": {"value": mph_45_ms}},
            {"distanceToNextSpeedLimit": 120000.0, "value": {"value": 11.18}},
        ],
    }
    limits = build_speed_limits_queue(data)
    assert len(limits) == 2
    assert limits[0]["distance_m"] == 297.0
    assert abs(limits[0]["limit_mph"] - 45.0) < 1.0
    assert limits[1]["distance_m"] == 1200.0


def test_parse_door_state_dmi_messages():
    from tsw6.telemetry.driver_aid_parser import parse_door_state

    open_msg = parse_door_state({
        "messages": [{"id": "dmi-doors-open"}],
    })
    assert open_msg["doors_dmi"] is True
    assert open_msg["doors_open"] is None

    closed_msg = parse_door_state({
        "messages": [{"id": "dmi-doors-closed"}],
    })
    assert closed_msg["doors_dmi"] is False
    assert closed_msg["doors_open"] is None


def test_parse_passenger_door_api():
    from tsw6.telemetry.driver_aid_parser import parse_passenger_door_api

    assert parse_passenger_door_api({"ReturnValue": 0.0}, {"ReturnValue": 0.0}) is False
    assert parse_passenger_door_api({"ReturnValue": 0.0}, {"ReturnValue": 1.0}) is True
    assert parse_passenger_door_api(None, None) is None


def test_resolve_station_door_state():
    from tsw6.telemetry.driver_aid_parser import resolve_station_door_state

    open_flag, src = resolve_station_door_state(
        doors_telem=False, doors_dmi=True)
    assert open_flag is True
    assert src == "dmi-open"

    closed_flag, src = resolve_station_door_state(
        doors_telem=False, doors_dmi=False)
    assert closed_flag is False
    assert src == "telem+dmi-closed"


def test_parse_driver_aid_planning_excludes_doors():
    data = {
        "distanceToNextSpeedLimit": 50000.0,
        "nextSpeedLimit": {"value": 20.12},
        "messages": [{"id": "dmi-doors-open"}],
    }
    out = parse_driver_aid_planning(data)
    assert "doors_dmi" not in out
    assert "doors_open" not in out
    assert "doors_telem" not in out
    assert "gradient_pct" not in out


def test_parse_track_data_stations_dedup():
    track = {
        "markers": [
            {
                "markerType": "Platform",
                "markerName": "Lichfield City, andén 2",
                "distanceToStationCM": 4700.0,
                "platformLength": 20000.0,
            },
            {
                "markerType": "Platform",
                "markerName": "Shenstone",
                "distanceToStationCM": 120000.0,
                "platformLength": 15000.0,
            },
        ],
    }
    st = parse_track_data_stations(track)
    assert len(st) == 2
    assert st[0]["name"].startswith("Lichfield")
    assert st[0]["distance_m"] == 47.0
    assert st[0]["platform_length_m"] == 200.0
    assert st[0]["scheduled"] is True


def test_parse_track_data_ignores_unnamed_platforms():
    """``stations[]`` sin markerName no son paradas del horario."""
    track = {
        "markers": [
            {
                "markerType": "Platform",
                "markerName": "Lichfield City, andén 2",
                "distanceToStationCM": 65125.0,
                "platformLength": 22735.0,
            },
        ],
        "stations": [
            {
                "markerType": "Platform",
                "markerName": "",
                "stationName": "Shenstone",
                "distanceToStationCM": 42389.0,
                "platformLength": 22735.0,
            },
            {
                "markerType": "Platform",
                "markerName": "",
                "stationName": "",
                "distanceToStationCM": 62056.0,
                "platformLength": 22735.0,
            },
        ],
    }
    st = parse_track_data_stations(track)
    assert len(st) == 1
    assert "Lichfield" in st[0]["name"]


def test_filter_stations_by_service_headcode():
    timetable = {
        "2R17": ["Lichfield City", "Birmingham New Street"],
    }
    stations = [
        {"name": "Lichfield City, andén 2", "distance_m": 500.0, "scheduled": True},
        {"name": "Shenstone", "distance_m": 1200.0, "scheduled": True},
        {"name": "Birmingham New Street", "distance_m": 8000.0, "scheduled": True},
    ]
    out = filter_stations_by_service(stations, timetable, "2R17")
    assert len(out) == 2
    assert {station_base_name(s["name"]) for s in out} == {
        "lichfield city", "birmingham new street"
    }


def test_select_next_scheduled_stop_skips_passed():
    stops = [
        {"name": "A", "distance_m": 30.0, "scheduled": True},
        {"name": "B", "distance_m": 800.0, "scheduled": True},
    ]
    nxt = select_next_scheduled_stop(stops, min_distance_m=100.0)
    assert nxt is not None
    assert nxt["name"] == "B"


def test_select_next_scheduled_stop_exclude_served():
    stops = [
        {"name": "Four Oaks", "distance_m": 0.0, "scheduled": True},
        {"name": "Sutton Coldfield", "distance_m": 11000.0, "scheduled": True},
    ]
    nxt = select_next_scheduled_stop(
        stops, min_distance_m=100.0, exclude_bases={"four oaks"},
    )
    assert nxt is not None
    assert nxt["name"] == "Sutton Coldfield"


def test_resolve_display_next_stop_uses_hud_when_track_lags():
    """Tras servir la primera, HUD indica la segunda aunque TrackData solo tenga la actual."""
    stops = [
        {"name": "Four Oaks", "distance_m": 0.0, "scheduled": True},
    ]
    nxt = resolve_display_next_stop(
        stops,
        exclude_bases={"four oaks"},
        hud_stop_names=["Four Oaks", "Sutton Coldfield", "Birmingham New Street"],
    )
    assert nxt is not None
    assert nxt["name"] == "Sutton Coldfield"
