"""Tests de driver_aid_parser."""

from driver_aid_parser import (
    build_speed_limits_queue,
    parse_driver_aid_planning,
    parse_gradient_pct,
    parse_track_data_stations,
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
