"""Reglas cartel↔andén agrupados (Four Oaks / Sutton)."""

from __future__ import annotations

from typing import Optional

from tsw6v2.constants import LIMIT_OVER_ACTIVE_MPH, posted_scoring_ceiling_mph
from tsw6v2.physics import TARGET_CLUSTER_GAP_M, projected_speed_mph_at_distance
from tsw6v2.target import LIMIT_SCORING_MAX_OVER_MPH, LIMIT_SIGN_PASSED_M


def targets_are_clustered(
    limit_dist_m: float,
    station_dist_m: float,
    cluster_gap_m: float = TARGET_CLUSTER_GAP_M,
) -> bool:
    if limit_dist_m <= 0 or station_dist_m <= 0:
        return False
    return abs(station_dist_m - limit_dist_m) <= cluster_gap_m


def should_merge_limit_and_station_plans(
    limit_dist_m: float,
    station_dist_m: float,
    cluster_gap_m: float = TARGET_CLUSTER_GAP_M,
) -> bool:
    if limit_dist_m > station_dist_m:
        return False
    return targets_are_clustered(limit_dist_m, station_dist_m, cluster_gap_m)


def cluster_approach_in_range(
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
) -> bool:
    """Cartel y andén en el mismo tramo cluster (±350 m), cartel no pasado."""
    if limit_dist_m is None or station_dist_m is None:
        return False
    if limit_dist_m <= LIMIT_SIGN_PASSED_M or station_dist_m <= 0:
        return False
    return limit_dist_m <= station_dist_m + TARGET_CLUSTER_GAP_M


def will_be_below_limit_at_pass(
    *,
    speed_mph: float,
    limit_mph: float,
    limit_dist_m: float,
    gradient_pct: float = 0.0,
    accel_ms2: float | None = None,
) -> bool:
    """Ya legal respecto al cartel y la proyección al pasarlo sigue bajo techo TSW."""
    if limit_dist_m <= LIMIT_SIGN_PASSED_M:
        return speed_mph <= posted_scoring_ceiling_mph(limit_mph)
    ceiling = posted_scoring_ceiling_mph(limit_mph)
    if speed_mph > ceiling:
        return False
    projected = projected_speed_mph_at_distance(
        speed_mph,
        limit_dist_m,
        accel_ms2=accel_ms2,
        gradient_pct=gradient_pct,
    )
    return projected <= ceiling


def station_may_ignore_limit_approach(
    *,
    speed_mph: float,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    gradient_pct: float = 0.0,
    accel_ms2: float | None = None,
) -> bool:
    """
    Cartel **delante** del andén en cluster y proyección legal al pasarlo.

    Centraliza la subregla usada por ``station_waits``, ``merged_approach_overspeed``,
    ``should_delay_unified_station_plan`` y ``should_prefer_station_in_approach``.
    """
    if limit_mph is None or not cluster_approach_in_range(limit_dist_m, station_dist_m):
        return False
    assert limit_dist_m is not None and station_dist_m is not None
    if limit_dist_m >= station_dist_m:
        return False
    return will_be_below_limit_at_pass(
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    )


def next_sign_is_reduction_beyond_station(
    *,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    current_limit_mph: Optional[float] = None,
) -> bool:
    """Recorte con HUD invertido (andén más cerca que cartel 55 en cluster).

    No aplica si el ``next`` del probe queda **más allá del andén** (p. ej. 45 mph
    @ 964 m con andén @ 281 m tras pasar el 55) — sesión 20260909T230944Z.
    """
    if limit_mph is None or limit_dist_m is None or station_dist_m is None:
        return False
    if limit_dist_m <= LIMIT_SIGN_PASSED_M or station_dist_m <= 0:
        return False
    if limit_dist_m <= station_dist_m + LIMIT_SIGN_PASSED_M:
        return False
    # Cartel posterior al andén (fuera del cluster): parada, no esperar recorte.
    if limit_dist_m > station_dist_m + TARGET_CLUSTER_GAP_M:
        return False
    if current_limit_mph is not None and limit_mph >= current_limit_mph - 0.1:
        return False
    return True


def station_waits_for_approach_limit(
    *,
    speed_mph: float,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    current_limit_mph: Optional[float] = None,
    gradient_pct: float = 0.0,
    accel_ms2: float | None = None,
) -> bool:
    if next_sign_is_reduction_beyond_station(
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        current_limit_mph=current_limit_mph,
    ):
        return True
    if limit_mph is None or not cluster_approach_in_range(limit_dist_m, station_dist_m):
        return False
    if station_may_ignore_limit_approach(
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    ):
        return False
    return speed_mph > limit_mph + LIMIT_SCORING_MAX_OVER_MPH


def merged_approach_overspeed(
    *,
    speed_mph: float,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    min_ahead_m: float = 50.0,
    over_mph: float = LIMIT_OVER_ACTIVE_MPH,
    gradient_pct: float = 0.0,
    accel_ms2: float | None = None,
) -> bool:
    if limit_mph is None or limit_dist_m is None or station_dist_m is None:
        return False
    if not should_merge_limit_and_station_plans(limit_dist_m, station_dist_m):
        return False
    if limit_dist_m <= min_ahead_m:
        return False
    if station_may_ignore_limit_approach(
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    ):
        return False
    return speed_mph > limit_mph + over_mph
