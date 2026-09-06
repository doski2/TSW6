"""Reglas cartel↔andén agrupados (FSM estación; antes policy.py v1)."""

from __future__ import annotations

from typing import Optional

from tsw6v2.command import LIMIT_OVER_ACTIVE_MPH
from tsw6v2.physics import TARGET_CLUSTER_GAP_M
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


def next_sign_is_reduction_beyond_station(
    *,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    current_limit_mph: Optional[float] = None,
) -> bool:
    if limit_mph is None or limit_dist_m is None or station_dist_m is None:
        return False
    if limit_dist_m <= LIMIT_SIGN_PASSED_M or station_dist_m <= 0:
        return False
    if limit_dist_m <= station_dist_m + LIMIT_SIGN_PASSED_M:
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
) -> bool:
    if next_sign_is_reduction_beyond_station(
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        current_limit_mph=current_limit_mph,
    ):
        return True
    if limit_mph is None or limit_dist_m is None or station_dist_m is None:
        return False
    if limit_dist_m <= LIMIT_SIGN_PASSED_M or station_dist_m <= 0:
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
) -> bool:
    if limit_mph is None or limit_dist_m is None or station_dist_m is None:
        return False
    if not should_merge_limit_and_station_plans(limit_dist_m, station_dist_m):
        return False
    if limit_dist_m <= min_ahead_m:
        return False
    return speed_mph > limit_mph + over_mph
