#!/usr/bin/env python3
"""
driver_aid_parser.py — Planning desde DriverAid (HTTPAPI).

Convierte ``DriverAid.Data`` y ``DriverAid.TrackData`` al formato que esperan
``build_train_state()``, ``BrakingAdvisor`` (P1) y ``StationFSM``.
"""

from __future__ import annotations

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


def parse_track_data_stations(track: Any) -> list[dict[str, Any]]:
    """Paradas programadas desde ``DriverAid.TrackData`` (markers / stations)."""
    if not isinstance(track, dict):
        return []

    seen: dict[str, dict[str, Any]] = {}

    def _add(name: str, dist_m: float, plat_m: Optional[float]) -> None:
        label = name.strip() or f"Parada@{dist_m:.0f}m"
        base = label.split(",")[0].strip().lower() or str(round(dist_m))
        entry: dict[str, Any] = {"name": label, "distance_m": round(dist_m, 1)}
        if plat_m is not None and plat_m > 0:
            entry["platform_length_m"] = round(plat_m, 1)
        prev = seen.get(base)
        if prev is None or dist_m < prev["distance_m"]:
            seen[base] = entry

    for item in track.get("markers") or []:
        if not isinstance(item, dict):
            continue
        mtype = str(item.get("markerType") or "").strip().lower()
        if mtype and mtype != "platform":
            continue
        dist_m = _cm_to_m(item.get("distanceToStationCM"))
        if dist_m is None:
            continue
        name = str(item.get("markerName") or item.get("stationName") or "")
        plat_m = _cm_to_m(item.get("platformLength"))
        _add(name, dist_m, plat_m)

    for item in track.get("stations") or []:
        if not isinstance(item, dict):
            continue
        dist_m = _cm_to_m(item.get("distanceToStationCM"))
        if dist_m is None:
            continue
        name = str(item.get("markerName") or item.get("stationName") or "")
        plat_m = _cm_to_m(item.get("platformLength"))
        _add(name, dist_m, plat_m)

    return sorted(seen.values(), key=lambda x: x["distance_m"])
