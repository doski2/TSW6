"""Horario HUD (``tsw_hud.db``) para planning de andén V2.

Lee la BD con ``tsw6v2.hud_db`` (propio de V2). Sin ``tsw6/``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from tsw6v2.hud_db import open_readonly, stops_for_service
from tsw6v2.track_stations import (
    filter_stations_by_stop_names,
    resolve_display_next_stop,
)

_log = logging.getLogger("tsw6v2.hud_schedule")


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
    hud_db_path: Optional[Path],
) -> Optional[dict[str, Any]]:
    """Paradas del servicio desde ``tsw_hud.db``; ``None`` si no hay BD o no hay match."""
    if hud_db_path is None:
        return None
    try:
        conn = open_readonly(hud_db_path)
    except Exception as exc:
        _log.debug("HUD DB no disponible: %s", exc)
        return None
    try:
        for variant in service_name_variants(service_name):
            stops = stops_for_service(conn, variant)
            if stops:
                return {
                    "service_name": variant,
                    "stop_names": [s.name for s in stops],
                    "stops": stops,
                }
    except Exception as exc:
        _log.warning("HUD query fallo (svc=%s): %s", service_name, exc)
    finally:
        conn.close()
    return None


def apply_station_schedule(
    track_stations: list[dict[str, Any]],
    service_name: Optional[str],
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    hud_db_path: Optional[Path] = None,
    fallback_all_when_unmatched: bool = True,
) -> tuple[list[dict[str, Any]], str, Optional[dict[str, Any]]]:
    """Filtra ``TrackData.markers`` con el horario HUD.

    Returns:
        (estaciones, schedule_source, hud_match)
        schedule_source: ``hud_db`` | ``track_only``
    """
    if not track_stations:
        return [], "none", None

    svc = (service_name or "").strip()
    if svc:
        resolved = resolve_hud_service_stops(svc, hud_db_path=hud_db_path)
        if resolved:
            matched = filter_stations_by_stop_names(
                track_stations, resolved["stop_names"]
            )
            if matched:
                return matched, "hud_db", resolved
            if not fallback_all_when_unmatched:
                # Servicio conocido pero su siguiente parada aún no sale en TrackData: sin
                # parada próxima (no frenar para una estación que no está en el horario).
                return [], "hud_db", resolved

    return track_stations, "track_only", None


def pick_next_scheduled_stop(
    stations: list[dict[str, Any]],
    *,
    hud_match: Optional[dict[str, Any]] = None,
    min_distance_m: float = 100.0,
    exclude_bases: Optional[set[str]] = None,
) -> Optional[dict[str, Any]]:
    hud_names = hud_match.get("stop_names") if hud_match else None
    return resolve_display_next_stop(
        stations,
        hud_stop_names=hud_names,
        min_distance_m=min_distance_m,
        exclude_bases=exclude_bases,
    )
