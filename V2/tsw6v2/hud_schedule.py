"""Horario HUD (``tsw_hud.db``) para planning de andén V2 — misma lógica que autopilot v1."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Optional

from tsw6.telemetry.driver_aid_parser import (
    filter_stations_by_stop_names,
    filter_stations_by_service,
    resolve_display_next_stop,
)

from tsw6v2.driver_aid_stations import load_service_timetable

_log = logging.getLogger("tsw6v2.hud_schedule")

_HUD_STORE: Any = None
_HUD_TRIED = False


def _hud_store() -> Any:
    """``HudTimetableStore`` lazy; ``None`` si no hay BD."""
    global _HUD_STORE, _HUD_TRIED
    if _HUD_TRIED:
        return _HUD_STORE
    _HUD_TRIED = True
    try:
        from tsw6.hud.hud_timetable import HudTimetableStore

        store = HudTimetableStore()
        if store.available:
            _HUD_STORE = store
            _log.info("HUD timetable: %s", store.db_path)
        else:
            _HUD_STORE = None
    except Exception as exc:
        _log.debug("HUD timetable no disponible: %s", exc)
        _HUD_STORE = None
    return _HUD_STORE


def player_geo_from_info(info: Any) -> tuple[Optional[float], Optional[float]]:
    if not isinstance(info, dict):
        return None, None
    geo = info.get("geoLocation") or info.get("playerPosition")
    if not isinstance(geo, dict):
        return None, None
    lat_raw = geo.get("latitude")
    lng_raw = geo.get("longitude")
    if lat_raw is None or lng_raw is None:
        return None, None
    try:
        return float(lat_raw), float(lng_raw)
    except (TypeError, ValueError):
        return None, None


def service_name_variants(service_name: str) -> list[str]:
    """Variantes para match en SQLite (título HUD, headcode, 5U02↔5O02)."""
    s = (service_name or "").strip()
    if not s:
        return []
    out: list[str] = []
    for cand in (s, s.split()[0]):
        if cand and cand not in out:
            out.append(cand)
    head = out[-1] if out else ""
    if len(head) >= 3 and head[0].isdigit() and head[1] in ("U", "O"):
        alt = head[0] + ("O" if head[1] == "U" else "U") + head[2:]
        if alt not in out:
            out.append(alt)
    return out


def resolve_hud_service_stops(
    service_name: str,
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    store = _hud_store()
    if store is None:
        return None
    for variant in service_name_variants(service_name):
        try:
            resolved = store.resolve_service_stops(variant, lat=lat, lng=lng)
        except sqlite3.Error as exc:
            _log.warning("HUD query fallo (svc=%s): %s", variant, exc)
            return None
        if resolved:
            return resolved
    return None


def apply_station_schedule(
    track_stations: list[dict[str, Any]],
    service_name: Optional[str],
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    timetable: Optional[dict[str, list[str]]] = None,
) -> tuple[list[dict[str, Any]], str, Optional[dict[str, Any]]]:
    """
    Filtra ``TrackData.markers`` con horario HUD o ``timetable.json``.

    Returns:
        (estaciones, schedule_source, hud_match)
        schedule_source: ``hud_db`` | ``timetable_json`` | ``track_only``
    """
    if not track_stations:
        return [], "none", None

    svc = (service_name or "").strip()
    timetable = timetable if timetable is not None else load_service_timetable()

    if svc:
        resolved = resolve_hud_service_stops(svc, lat=lat, lng=lng)
        if resolved:
            store = _hud_store()
            matched = filter_stations_by_stop_names(
                track_stations, resolved["stop_names"]
            )
            merged: list[dict[str, Any]] = []
            if store is not None:
                merged = store.merge_schedule_stations(
                    matched,
                    resolved["entries"],
                    resolved["stop_names"],
                    lat=lat,
                    lng=lng,
                )
            if merged:
                return merged, "hud_db", resolved
            if matched:
                return matched, "hud_db", resolved

    if timetable:
        filtered = filter_stations_by_service(track_stations, timetable, svc or None)
        if filtered is not track_stations:
            return filtered, "timetable_json", None

    return track_stations, "track_only", None


def pick_next_scheduled_stop(
    stations: list[dict[str, Any]],
    *,
    hud_match: Optional[dict[str, Any]] = None,
    min_distance_m: float = 100.0,
) -> Optional[dict[str, Any]]:
    hud_names = hud_match.get("stop_names") if hud_match else None
    return resolve_display_next_stop(
        stations,
        hud_stop_names=hud_names,
        min_distance_m=min_distance_m,
    )
