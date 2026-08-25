#!/usr/bin/env python3
"""Utilidades cartel ↔ estación (cluster 350 m)."""

from __future__ import annotations

from typing import Optional

from tsw6.braking.v2.physics import (
    DEFAULT_MAX_BRAKE_DECEL,
    TARGET_CLUSTER_GAP_M,
    BrakePhysicsContext,
    braking_distance_mph,
    decel_for_notch,
)


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
    if not targets_are_clustered(limit_dist_m, station_dist_m, cluster_gap_m):
        return False
    return limit_dist_m <= station_dist_m


def sequential_limit_stop_feasible(
    *,
    limit_mph: float,
    limit_dist_m: float,
    station_dist_m: float,
    gradient_pct: float = 0.0,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
    safety_margin_m: float = 40.0,
) -> bool:
    if limit_dist_m <= 0 or station_dist_m <= limit_dist_m:
        return False
    gap_m = station_dist_m - limit_dist_m
    decel = decel_for_notch(0.80, base_decel, gradient_pct)
    stop_after_limit = braking_distance_mph(
        limit_mph,
        0.0,
        decel_ms2=decel,
        ctx=BrakePhysicsContext(
            base_decel_ms2=base_decel,
            gradient_pct=gradient_pct,
        ),
        apply_margin=False,
    )
    return gap_m >= stop_after_limit + safety_margin_m


UNIFIED_STATION_LIMIT_APPROACH_M = 200.0


def should_delay_unified_station_plan(
    *,
    speed_mph: float,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    approach_m: float = UNIFIED_STATION_LIMIT_APPROACH_M,
) -> bool:
    """
    Ya a velocidad del cartel: esperar antes de planificar parada unificada.

    Evita B1 a cientos de metros del cartel cuando el tramo cartel→andén
    aún permite coast al límite intermedio.
    """
    if limit_mph is None or limit_dist_m is None or station_dist_m is None:
        return False
    if limit_dist_m <= approach_m:
        return False
    if speed_mph > limit_mph + 3.0:
        return False
    gap_m = station_dist_m - limit_dist_m
    if gap_m <= 0 or gap_m > TARGET_CLUSTER_GAP_M:
        return False
    return True
