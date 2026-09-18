"""Paradas programadas desde ``DriverAid.TrackData`` (HTTPAPI)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from tsw6.telemetry.driver_aid_parser import (
    SCHEDULED_STOP_MIN_AHEAD_M,
    filter_stations_by_service,
    load_service_timetable,
    parse_track_data_stations,
    select_next_scheduled_stop,
    station_base_name,
)

__all__ = [
    "SCHEDULED_STOP_MIN_AHEAD_M",
    "filter_stations_by_service",
    "load_service_timetable",
    "parse_track_data_stations",
    "poll_station_planning",
    "select_next_scheduled_stop",
    "station_base_name",
]


def poll_station_planning(
    *,
    api_key: Optional[str] = None,
    timetable_path: Optional[Path] = None,
    exclude_bases: Optional[set[str]] = None,
) -> dict[str, Any]:
    """
    Una lectura HTTP: TrackData + PlayerInfo → estaciones filtradas y próxima parada.

    Horario: ``tsw_hud.db`` si está disponible; si no, ``timetable.json``.
    """
    from tsw6v2.bridge.http_api import get_driver_aid_node
    from tsw6v2.hud_schedule import (
        apply_station_schedule,
        pick_next_scheduled_stop,
        player_geo_from_info,
    )

    out: dict[str, Any] = {}
    track = get_driver_aid_node("DriverAid.TrackData", api_key=api_key)
    raw_stations: list[dict[str, Any]] = []
    if track is not None:
        raw_stations = parse_track_data_stations(track)
        if raw_stations:
            out["stations_raw"] = raw_stations

    info = get_driver_aid_node("DriverAid.PlayerInfo", api_key=api_key)
    service_name: Optional[str] = None
    lat = lng = None
    if isinstance(info, dict):
        svc = info.get("currentServiceName")
        if svc:
            service_name = str(svc).strip()
            out["service_name"] = service_name
        lat, lng = player_geo_from_info(info)

    if raw_stations:
        timetable = load_service_timetable(timetable_path)
        stations, schedule_source, hud_match = apply_station_schedule(
            raw_stations,
            service_name,
            lat=lat,
            lng=lng,
            timetable=timetable,
        )
        out["stations"] = stations
        out["schedule_source"] = schedule_source
        if hud_match:
            out["hud_timetable_id"] = hud_match.get("timetable_id")
            out["hud_route_name"] = hud_match.get("route_name")
            out["hud_stop_names"] = hud_match.get("stop_names")
        nxt = pick_next_scheduled_stop(
            stations,
            hud_match=hud_match,
            exclude_bases=exclude_bases,
        )
        if nxt is not None:
            out["next_stop"] = nxt
    return out
