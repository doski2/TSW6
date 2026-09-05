"""Extrae objetivos P1 desde GetData (probe)."""

from __future__ import annotations

from typing import Optional

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.constants import MS_TO_MPH


def next_speed_limit(snap: Optional[ProbeSnapshot]) -> tuple[Optional[float], Optional[float]]:
    """(distancia_m, límite_mph) del primer cartel en GetData."""
    if snap is None:
        return None, None
    if snap.dist_limit_cm is None or snap.next_limit_ms is None:
        return None, None
    dist_m = float(snap.dist_limit_cm) / 100.0
    limit_mph = float(snap.next_limit_ms) * MS_TO_MPH
    if dist_m <= 0 or limit_mph <= 0:
        return None, None
    return dist_m, limit_mph


def effective_limit_mph(snap: Optional[ProbeSnapshot], *, fallback_mph: float = 125.0) -> float:
    """Límite vigente (speed_limit_ms) o cartel adelante; fallback line speed."""
    if snap is None:
        return fallback_mph
    if snap.speed_limit_ms is not None and snap.speed_limit_ms > 0:
        return float(snap.speed_limit_ms) * MS_TO_MPH
    _dist, next_mph = next_speed_limit(snap)
    if next_mph is not None:
        return next_mph
    return fallback_mph

