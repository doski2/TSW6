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


def _cm_to_m(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        v = float(raw) * CM_TO_M
    except (TypeError, ValueError):
        return None
    if v <= 0 or _is_sentinel(v):
        return None
    return v


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

    dist_m = _cm_to_m(data.get("distanceToNextSpeedLimit"))
    next_ms = _scalar_ms(data.get("nextSpeedLimit"))
    if next_ms is not None:
        out["next_limit_mph"] = float(next_ms) * MS_TO_MPH
    if dist_m is not None:
        out["distance_next_m"] = dist_m

    limits: list[dict[str, float]] = []
    for item in data.get("nextSpeedLimits") or []:
        if not isinstance(item, dict):
            continue
        d_m = _cm_to_m(item.get("distanceToNextSpeedLimit"))
        lim_ms = _scalar_ms(item.get("value"))
        if d_m is None or lim_ms is None:
            continue
        limits.append({
            "limit_mph": round(float(lim_ms) * MS_TO_MPH, 1),
            "distance_m": round(d_m, 1),
        })
    limits.sort(key=lambda x: x["distance_m"])
    if limits:
        out["speed_limits_ahead"] = limits
        if out.get("next_limit_mph") is None:
            out["next_limit_mph"] = limits[0]["limit_mph"]
        if out.get("distance_next_m") is None:
            out["distance_next_m"] = limits[0]["distance_m"]

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
