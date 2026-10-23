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
        "service_name": "5U02",
        "stop_names": ["Four Oaks"],
        "stops": [],
    }
    with patch("tsw6v2.hud_schedule.resolve_hud_service_stops", return_value=hud_match):
        filtered, src, match = apply_station_schedule(
            stations, "5U02 Birmingham New Street to Four Oaks", lat=52.48, lng=-1.90
        )
    assert src == "hud_db"
    assert match is hud_match
    assert len(filtered) == 1
    assert filtered[0]["name"] == "Four Oaks"


def test_apply_station_schedule_without_hud_is_track_only():
    stations = parse_track_data_stations(_track())
    with patch("tsw6v2.hud_schedule.resolve_hud_service_stops", return_value=None):
        filtered, src, match = apply_station_schedule(stations, "2R17")
    assert src == "track_only"
    assert match is None
    assert len(filtered) == len(stations)


def test_apply_station_schedule_unmatched_service_offers_no_unscheduled_stop_203040z():
    """Fordham→Harlem 125th: Tremont (no está en el horario) no debe ser la parada próxima."""
    stations = parse_track_data_stations(_track())
    hud_match = {"service_name": "500", "stop_names": ["Harlem 125th Street"], "stops": []}
    with patch("tsw6v2.hud_schedule.resolve_hud_service_stops", return_value=hud_match):
        filtered, src, match = apply_station_schedule(
            stations, "500", fallback_all_when_unmatched=False
        )
    assert filtered == [] and src == "hud_db" and match is hud_match
    # por defecto (nombres que nunca cuadran) se mantiene el respaldo track_only
    with patch("tsw6v2.hud_schedule.resolve_hud_service_stops", return_value=hud_match):
        filtered, src, _ = apply_station_schedule(stations, "500")
    assert src == "track_only" and len(filtered) == len(stations)


def test_poll_station_planning_uses_service_hint_when_player_info_fails_203040z():
    """PlayerInfo intermitente: sin pista el poll caía a track_only y perdía el horario."""
    from tsw6v2.driver_aid_stations import poll_station_planning

    def fake_node(node, api_key=None, **_):
        return _track() if node.endswith("TrackData") else None  # PlayerInfo falla

    seen: dict[str, object] = {}

    def fake_apply(stations, service_name, **kw):
        seen["service"] = service_name
        seen["fallback"] = kw.get("fallback_all_when_unmatched")
        return stations, "hud_db", None

    with (
        patch("tsw6v2.bridge.http_api.get_driver_aid_node", side_effect=fake_node),
        patch("tsw6v2.hud_schedule.apply_station_schedule", side_effect=fake_apply),
    ):
        poll_station_planning(service_name_hint="500", fallback_all_when_unmatched=False)
    assert seen == {"service": "500", "fallback": False}


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


def test_unscheduled_station_not_offered_while_scheduled_stop_is_far_20261023():
    """Servicio 2307 (única parada: Crestwood, ~19 km): Harlem 125th no es parada del horario.

    Antes ``fallback_all_when_unmatched`` (activo hasta el primer match) devolvía todas las
    estaciones de ``TrackData`` y el agente frenaba para Harlem 125th.
    """
    from types import SimpleNamespace

    stations = parse_track_data_stations(_track())
    crestwood = SimpleNamespace(name="Crestwood", latitude=40.9598668, longitude=-73.8204233)
    hud_match = {"service_name": "2307", "stop_names": ["Crestwood"], "stops": [crestwood]}
    harlem = (40.8053, -73.9386)  # ~19 km de Crestwood
    with patch("tsw6v2.hud_schedule.resolve_hud_service_stops", return_value=hud_match):
        filtered, src, match = apply_station_schedule(
            stations, "2307", lat=harlem[0], lng=harlem[1], fallback_all_when_unmatched=True
        )
    assert filtered == [] and src == "hud_db" and match is hud_match


def test_scheduled_stop_near_but_unmatched_keeps_track_only_fallback():
    """A menos de 3 km que no salga en TrackData indica nombres que no cuadran: respaldo."""
    from types import SimpleNamespace

    stations = parse_track_data_stations(_track())
    near = SimpleNamespace(name="Crestwood", latitude=40.9598, longitude=-73.8204)
    hud_match = {"service_name": "2307", "stop_names": ["Crestwood"], "stops": [near]}
    with patch("tsw6v2.hud_schedule.resolve_hud_service_stops", return_value=hud_match):
        filtered, src, _ = apply_station_schedule(
            stations, "2307", lat=40.9600, lng=-73.8210, fallback_all_when_unmatched=True
        )
    assert src == "track_only" and len(filtered) == len(stations)


def test_scheduled_stops_beyond_trackdata_needs_position_and_coordinates():
    from types import SimpleNamespace

    from tsw6v2.hud_schedule import scheduled_stops_beyond_trackdata

    far = {"stops": [SimpleNamespace(latitude=40.9598, longitude=-73.8204)]}
    assert scheduled_stops_beyond_trackdata(far, 40.8053, -73.9386) is True
    assert scheduled_stops_beyond_trackdata(far, None, None) is False
    assert scheduled_stops_beyond_trackdata({"stops": []}, 40.8, -73.9) is False
    nocoords = {"stops": [SimpleNamespace(latitude=None, longitude=None)]}
    assert scheduled_stops_beyond_trackdata(nocoords, 40.8, -73.9) is False
