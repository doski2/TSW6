"""Paradas desde ``DriverAid.TrackData`` (HTTPAPI) y filtrado por horario.

Port mínimo de ``tsw6.telemetry.driver_aid_parser`` para que V2 no dependa de
``tsw6/``. Solo contiene lo que usa V2; el horario sale de ``hud_db``.
"""

from __future__ import annotations

from typing import Any, Optional

CM_TO_M = 0.01
_SENTINEL = 3.4028235e38

# Andenes más cercanos se tratan como ya pasados si hay otra parada más lejos.
SCHEDULED_STOP_MIN_AHEAD_M = 100.0


def _is_sentinel(val: float) -> bool:
    return val >= _SENTINEL * 0.99 or val != val  # NaN


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
    """Nombre corto para comparar con horario (antes de la coma)."""
    return str(name or "").split(",")[0].strip().lower()


def filter_stations_by_stop_names(
    stations: list[dict[str, Any]],
    stop_names: list[str],
) -> list[dict[str, Any]]:
    """Filtra andenes por nombres de parada (p. ej. desde ``tsw_hud.db``)."""
    if not stations:
        return []
    if not stop_names:
        return stations
    allowed = {station_base_name(n) for n in stop_names}
    return [
        st for st in stations
        if station_base_name(str(st.get("name", ""))) in allowed
    ]


def _station_marker_label(item: dict[str, Any]) -> str:
    """Parada programada: solo ``markerName`` (no ``stationName`` suelto)."""
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
        "raw_distance_cm": float(item["distanceToStationCM"]),
        "scheduled": True,
    }
    if plat_m is not None and plat_m > 0:
        entry["platform_length_m"] = round(plat_m, 1)
    return entry


def parse_track_data_stations(track: Any) -> list[dict[str, Any]]:
    """Paradas programadas desde ``DriverAid.TrackData.markers``.

    Solo entradas con ``markerName`` no vacío (``markerType: Platform``).
    Una entrada por nombre base, la más cercana.
    """
    if not isinstance(track, dict):
        return []

    seen: dict[str, dict[str, Any]] = {}
    for item in track.get("markers") or []:
        entry = _track_marker_entry(item)
        if entry is None:
            continue
        base = station_base_name(entry["name"])
        if not base:
            continue
        prev = seen.get(base)
        if prev is None or entry["distance_m"] < prev["distance_m"]:
            seen[base] = entry

    return sorted(seen.values(), key=lambda x: x["distance_m"])


def select_next_scheduled_stop(
    stations: Optional[list],
    *,
    min_distance_m: float = SCHEDULED_STOP_MIN_AHEAD_M,
    exclude_bases: Optional[set[str]] = None,
) -> Optional[dict[str, Any]]:
    """Próxima parada: la más cercana adelante con nombre.

    Ignora andenes ya pasados (< ``min_distance_m``) salvo que no quede otra.
    ``exclude_bases`` excluye paradas ya servidas (nombres base en minúsculas).
    """
    if not stations:
        return None
    exclude = exclude_bases or set()
    scheduled = [s for s in stations if s.get("scheduled", True)]
    pool = scheduled or list(stations)
    pool = [
        s for s in pool
        if station_base_name(str(s.get("name", ""))) not in exclude
    ]
    if not pool:
        return None
    ahead = [s for s in pool if float(s.get("distance_m") or 0) > min_distance_m]
    if ahead:
        return min(ahead, key=lambda s: float(s["distance_m"]))
    return min(pool, key=lambda s: float(s.get("distance_m") or 0))


def resolve_display_next_stop(
    stations: Optional[list],
    *,
    exclude_bases: Optional[set[str]] = None,
    hud_stop_names: Optional[list[str]] = None,
    min_distance_m: float = SCHEDULED_STOP_MIN_AHEAD_M,
) -> Optional[dict[str, Any]]:
    """Próxima parada para GUI/P1, excluyendo andenes ya servidos.

    Si TrackData aún no lista la siguiente, usa el orden del horario HUD.
    """
    nxt = select_next_scheduled_stop(
        stations,
        min_distance_m=min_distance_m,
        exclude_bases=exclude_bases,
    )
    if nxt is not None:
        return nxt
    if not hud_stop_names:
        return None
    exclude = exclude_bases or set()
    track_by_base: dict[str, dict[str, Any]] = {}
    for st in stations or []:
        base = station_base_name(str(st.get("name", "")))
        if not base:
            continue
        prev = track_by_base.get(base)
        dist = float(st.get("distance_m") or 0)
        if prev is None or dist < float(prev.get("distance_m") or 0):
            track_by_base[base] = dict(st)
    for name in hud_stop_names:
        base = station_base_name(name)
        if not base or base in exclude:
            continue
        if base in track_by_base:
            return track_by_base[base]
        return {"name": name, "scheduled": True}
    return None
