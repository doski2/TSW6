"""Extrae objetivos P1 desde GetData (probe) y reglas de cartel."""

from __future__ import annotations

from typing import Optional

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.constants import (
    ASCENDING_EXIT_ZONE_HOLD_MIN_DELTA_MPH,
    ASCENDING_EXIT_ZONE_HOLD_MIN_POSTED_MPH,
    ASCENDING_LIMIT_DELTA_MPH,
    DESCENDING_LIMIT_DELTA_MPH,
    LIMIT_OVER_ACTIVE_MPH,
    MS_TO_MPH,
)


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


def is_ascending_limit_exit(
    posted_limit_mph: float,
    next_limit_mph: Optional[float],
    *,
    delta_mph: float = ASCENDING_LIMIT_DELTA_MPH,
) -> bool:
    """Cartel siguiente sube (ej. 35→60): no HOLD_DH; RELEASE respecto al posted."""
    return (
        next_limit_mph is not None
        and next_limit_mph > posted_limit_mph + delta_mph
    )


def should_skip_zone_hold_for_ascending_exit(
    posted_limit_mph: float,
    next_limit_mph: Optional[float],
) -> bool:
    """
    Salto grande (35→60): dejar subir hacia el cartel siguiente.

    Saltos moderados (10→30 en Cross-City): mantener HOLD_DH en zona lenta
    aunque el cartel suba (sesión 142034Z: 12 mph en zona 10 sin objetivo).

    Zonas muy lentas (posted < 30): siempre contener — 15→50 no anula el 15
    vigente (sesión 152129Z: 16 mph en bajada sin freno).
    """
    if not is_ascending_limit_exit(posted_limit_mph, next_limit_mph):
        return False
    if next_limit_mph is None:
        return False
    if posted_limit_mph < ASCENDING_EXIT_ZONE_HOLD_MIN_POSTED_MPH:
        return False
    return (
        next_limit_mph - posted_limit_mph
        >= ASCENDING_EXIT_ZONE_HOLD_MIN_DELTA_MPH
    )


def is_descending_limit_zone(
    posted_limit_mph: float,
    next_limit_mph: Optional[float],
    *,
    delta_mph: float = DESCENDING_LIMIT_DELTA_MPH,
) -> bool:
    """Cartel siguiente baja (ej. 60→55): solo BRAKE_LIMIT, sin HOLD_DH."""
    return (
        next_limit_mph is not None
        and next_limit_mph < posted_limit_mph - delta_mph
    )


def resolve_limit_objective(
    *,
    speed_mph: float,
    effective_limit: float,
    next_limit_mph: Optional[float],
    distance_next_m: Optional[float],
    speed_limits_ahead: Optional[list] = None,
) -> tuple[Optional[float], Optional[float]]:
    """Cartel adelante en cola, o límite vigente si ya lo violamos."""
    nl = next_limit_mph
    dn = distance_next_m
    limits_queue = list(speed_limits_ahead or [])
    if limits_queue:
        nl = limits_queue[0].get("limit_mph", nl)
        dn = limits_queue[0].get("distance_m", dn)
    if speed_mph > effective_limit + LIMIT_OVER_ACTIVE_MPH:
        next_inactive = (
            nl is None
            or dn is None
            or float(dn) <= 1.0
            or (nl is not None and float(nl) >= float(effective_limit) - 0.1)
        )
        if next_inactive:
            nl = float(effective_limit)
            dn = max(1.0, float(dn or 1.0))
    return nl, dn
