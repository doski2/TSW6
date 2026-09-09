"""Paradas programadas desde ``DriverAid.TrackData`` (HTTPAPI)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

CM_TO_M = 0.01
_SENTINEL = 3.4028235e38
SCHEDULED_STOP_MIN_AHEAD_M = 100.0


def _is_sentinel(val: float) -> bool:
    return val >= _SENTINEL * 0.99 or val != val


def _cm_to_m(raw: Any, *, reject_zero: bool = True) -> Optional[float]:
    if raw is None:
        return None
    try:
        v = float(raw) * CM_TO_M
    except (TypeError, ValueError):
        return None
    if v < 0 or _is_sentinel(v):
        return None
    if reject_zero and v <= 0:
        return None
    return v


def station_base_name(name: str) -> str:
    return str(name or "").split(",")[0].strip().lower()


def _station_marker_label(item: dict[str, Any]) -> str:
    return str(item.get("markerName") or "").strip()


def _is_platform_marker(item: dict[str, Any]) -> bool:
    mtype = str(item.get("markerType") or "Platform").strip().lower()
    return mtype in ("", "platform")


def _track_marker_entry(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not isinstance(item, dict) or not _is_platform_marker(item):
        return None
    dist_m = _cm_to_m(item.get("distanceToStationCM"))
    if dist_m is None:
        return None
    name = _station_marker_label(item)
    if not name:
        return None
    plat_m = _cm_to_m(item.get("platformLength"), reject_zero=False)
    entry: dict[str, Any] = {
        "name": name,
        "distance_m": round(dist_m, 1),
        "scheduled": True,
    }
    if plat_m is not None and plat_m > 0:
        entry["platform_length_m"] = round(plat_m, 1)
    return entry


def parse_track_data_stations(track: Any) -> list[dict[str, Any]]:
    """``markers[]`` con ``markerName`` — distancia al fin de plataforma (m)."""
    if not isinstance(track, dict):
        return []
    seen: dict[str, dict[str, Any]] = {}

    def _merge(entry: dict[str, Any]) -> None:
        base = station_base_name(entry["name"])
        if not base:
            return
        prev = seen.get(base)
        if prev is None or entry["distance_m"] < prev["distance_m"]:
            seen[base] = entry

    for item in track.get("markers") or []:
        entry = _track_marker_entry(item)
        if entry is not None:
            _merge(entry)
    return sorted(seen.values(), key=lambda x: x["distance_m"])


def load_service_timetable(path: Optional[Path] = None) -> dict[str, list[str]]:
    if path is None:
        path = Path(__file__).resolve().parents[2] / "data" / "timetable.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(k): list(v)
        for k, v in raw.items()
        if not str(k).startswith("_") and isinstance(v, list)
    }


def filter_stations_by_service(
    stations: list[dict[str, Any]],
    timetable: dict[str, list[str]],
    service_name: Optional[str],
) -> list[dict[str, Any]]:
    if not stations or not timetable:
        return stations
    if service_name and service_name in timetable:
        allowed = {station_base_name(s) for s in timetable[service_name]}
    else:
        allowed = {
            station_base_name(s)
            for stops in timetable.values()
            for s in stops
        }
    filtered = [
        st
        for st in stations
        if station_base_name(str(st.get("name", ""))) in allowed
    ]
    return filtered if filtered else stations


def select_next_scheduled_stop(
    stations: Optional[list],
    *,
    min_distance_m: float = SCHEDULED_STOP_MIN_AHEAD_M,
    exclude_bases: Optional[set[str]] = None,
) -> Optional[dict[str, Any]]:
    if not stations:
        return None
    exclude = exclude_bases or set()
    pool = [
        s
        for s in stations
        if station_base_name(str(s.get("name", ""))) not in exclude
    ]
    if not pool:
        return None
    ahead = [s for s in pool if float(s.get("distance_m") or 0) > min_distance_m]
    if ahead:
        return min(ahead, key=lambda s: float(s["distance_m"]))
    return min(pool, key=lambda s: float(s.get("distance_m") or 0))


def poll_station_planning(
    *,
    api_key: Optional[str] = None,
    timetable_path: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Una lectura HTTP: TrackData + PlayerInfo → estaciones filtradas y próxima parada.
    """
    from tsw6v2.bridge.http_api import get_driver_aid_node

    out: dict[str, Any] = {}
    track = get_driver_aid_node("DriverAid.TrackData", api_key=api_key)
    if track is not None:
        stations = parse_track_data_stations(track)
        if stations:
            out["stations"] = stations
    info = get_driver_aid_node("DriverAid.PlayerInfo", api_key=api_key)
    service_name: Optional[str] = None
    if isinstance(info, dict):
        svc = info.get("currentServiceName")
        if svc:
            service_name = str(svc).strip()
            out["service_name"] = service_name
    stations = out.get("stations")
    if stations:
        timetable = load_service_timetable(timetable_path)
        out["stations"] = filter_stations_by_service(
            stations, timetable, service_name
        )
        nxt = select_next_scheduled_stop(out["stations"])
        if nxt is not None:
            out["next_stop"] = nxt
    return out
