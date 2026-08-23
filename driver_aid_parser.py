#!/usr/bin/env python3
"""
driver_aid_parser.py — Planning desde DriverAid (HTTPAPI).

Convierte ``DriverAid.Data`` y ``DriverAid.TrackData`` al formato que esperan
``build_train_state()``, ``BrakingAdvisor`` (P1) y ``StationFSM``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

MS_TO_MPH = 2.236936
CM_TO_M = 0.01
_SENTINEL = 3.4028235e38


def _is_sentinel(val: float) -> bool:
    return val >= _SENTINEL * 0.99 or val != val  # NaN


def _scalar_ms(node: Any) -> Optional[float]:
    """Extrae m/s de un número o struct ``{value: …}``."""
    if node is None:
        return None
    if isinstance(node, (int, float)):
        v = float(node)
        if _is_sentinel(v) or v < 0:
            return None
        return v
    if isinstance(node, dict):
        for key in ("value", "Value"):
            if key in node:
                return _scalar_ms(node[key])
    return None


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


def _prune_zero_distance_limits(
    limits: list[dict[str, float]],
) -> list[dict[str, float]]:
    """Quita límites ya alcanzados (distancia 0 en cartel)."""
    while limits and limits[0].get("distance_m", 0) <= 1.0:
        limits.pop(0)
    return limits


def parse_gradient_pct(node: Any) -> Optional[float]:
    """Gradiente (%) desde DriverAid.Data."""
    if node is None:
        return None
    if isinstance(node, (int, float)):
        v = float(node)
        return None if _is_sentinel(v) else v
    if not isinstance(node, dict):
        return None
    for key in ("gradient", "Gradient", "gradient_percent"):
        if key not in node:
            continue
        val = node[key]
        if isinstance(val, dict):
            raw = val.get("Value", val.get("value"))
            if raw is not None:
                return float(raw)
        elif val is not None:
            return float(val)
    return None


def _merge_limit_entry(
    limits: list[dict[str, float]],
    dist_m: float,
    lim_mph: float,
    *,
    dedupe_m: float = 8.0,
) -> None:
    """Añade un límite a la cola si no hay otro a distancia similar."""
    for existing in limits:
        if abs(existing["distance_m"] - dist_m) <= dedupe_m:
            if lim_mph < existing["limit_mph"]:
                existing["limit_mph"] = round(lim_mph, 1)
            return
    limits.append({
        "limit_mph": round(float(lim_mph), 1),
        "distance_m": round(float(dist_m), 1),
    })


def build_speed_limits_queue(data: dict[str, Any]) -> list[dict[str, float]]:
    """
    Cola unificada de cambios de límite adelante (ordenada por distancia).

    Fusiona ``nextSpeedLimit`` + ``distanceToNextSpeedLimit`` con
    ``nextSpeedLimits[]`` para que P1 y la GUI vean al menos los 2 próximos.
    """
    limits: list[dict[str, float]] = []

    dist_m = _cm_to_m(data.get("distanceToNextSpeedLimit"))
    next_ms = _scalar_ms(data.get("nextSpeedLimit"))
    if next_ms is not None and dist_m is not None:
        _merge_limit_entry(limits, dist_m, float(next_ms) * MS_TO_MPH)

    for item in data.get("nextSpeedLimits") or []:
        if not isinstance(item, dict):
            continue
        d_m = _cm_to_m(item.get("distanceToNextSpeedLimit"))
        lim_ms = _scalar_ms(item.get("value"))
        if d_m is None or lim_ms is None:
            continue
        _merge_limit_entry(limits, d_m, float(lim_ms) * MS_TO_MPH)

    limits.sort(key=lambda x: x["distance_m"])
    return _prune_zero_distance_limits(limits)


def parse_driver_aid_planning(data: Any) -> dict[str, Any]:
    """
    Campos de planning para P1: próximo límite y cola de límites adelante.

    También incluye ``gradient_pct`` si viene en el mismo nodo.
    """
    out: dict[str, Any] = {}
    if not isinstance(data, dict):
        return out

    grad = parse_gradient_pct(data)
    if grad is not None:
        out["gradient_pct"] = grad

    limits = build_speed_limits_queue(data)
    if limits:
        out["speed_limits_ahead"] = limits
        out["next_limit_mph"] = limits[0]["limit_mph"]
        out["distance_next_m"] = limits[0]["distance_m"]
        if len(limits) > 1:
            out["next_limit_2_mph"] = limits[1]["limit_mph"]
            out["distance_next_2_m"] = limits[1]["distance_m"]

    return out


_TIMETABLE_PATH = Path(__file__).resolve().parent / "timetable.json"


def station_base_name(name: str) -> str:
    """Nombre corto para comparar con timetable (antes de la coma)."""
    return str(name or "").split(",")[0].strip().lower()


def load_service_timetable(path: Optional[Path] = None) -> dict[str, list[str]]:
    """Carga ``timetable.json`` — paradas programadas por headcode."""
    path = path or _TIMETABLE_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(k): list(v)
        for k, v in raw.items()
        if not str(k).startswith("_") and isinstance(v, list)
    }


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


def filter_stations_by_service(
    stations: list[dict[str, Any]],
    timetable: dict[str, list[str]],
    service_name: Optional[str],
) -> list[dict[str, Any]]:
    """
    Quita paradas de paso: solo las del horario del servicio activo.

    Si no hay servicio conocido, usa la unión de todos los servicios del
  timetable (excluye plataformas que no están en ningún horario cargado).
    """
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
        st for st in stations
        if station_base_name(str(st.get("name", ""))) in allowed
    ]
    return filtered if filtered else stations


def _station_marker_label(item: dict[str, Any]) -> str:
    """Parada programada: solo ``markerName`` (no ``stationName`` suelto)."""
    return str(item.get("markerName") or "").strip()


def _is_platform_marker(item: dict[str, Any]) -> bool:
    mtype = str(item.get("markerType") or "Platform").strip().lower()
    return mtype in ("", "platform")


def _track_marker_entry(
    item: dict[str, Any],
    *,
    scheduled: bool,
) -> Optional[dict[str, Any]]:
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
        "scheduled": scheduled,
    }
    if plat_m is not None and plat_m > 0:
        entry["platform_length_m"] = round(plat_m, 1)
    return entry


def parse_track_data_stations(track: Any) -> list[dict[str, Any]]:
    """
    Paradas programadas desde ``DriverAid.TrackData.markers``.

    Solo entradas con ``markerName`` no vacío (``markerType: Platform``).
    ``stations[]`` es geometría de andén — se ignora.
    Filtrar con ``filter_stations_by_service`` + ``timetable.json``.
    """
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
        entry = _track_marker_entry(item, scheduled=True)
        if entry is not None:
            _merge(entry)

    return sorted(seen.values(), key=lambda x: x["distance_m"])


def select_next_scheduled_stop(
    stations: Optional[list],
    *,
    min_distance_m: float = 100.0,
    exclude_bases: Optional[set[str]] = None,
) -> Optional[dict[str, Any]]:
    """
    Próxima parada del servicio (más cercana adelante con nombre).

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
