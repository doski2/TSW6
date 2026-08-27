#!/usr/bin/env python3
"""Utilidades cartel ↔ estación (cluster 350 m)."""

from __future__ import annotations

from typing import Optional

from tsw6.braking.v2.physics import (
    DEFAULT_MAX_BRAKE_DECEL,
    MPH_TO_MS,
    TARGET_CLUSTER_GAP_M,
    BrakePhysicsContext,
    brake_reaction_margin_m,
    braking_distance_mph,
    decel_for_notch,
    kinematic_horizon_m,
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


def is_unified_limit_station_stop(
    *,
    limit_mph: float,
    limit_dist_m: float,
    station_dist_m: float,
    gradient_pct: float = 0.0,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
) -> bool:
    """Cartel y andén agrupados y no cabe  v→límite, soltar, v→0."""
    if not should_merge_limit_and_station_plans(limit_dist_m, station_dist_m):
        return False
    return not sequential_limit_stop_feasible(
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        base_decel=base_decel,
    )


def sequential_limit_stop_feasible(
    *,
    limit_mph: float,
    limit_dist_m: float,
    station_dist_m: float,
    gradient_pct: float = 0.0,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
) -> bool:
    if limit_dist_m <= 0 or station_dist_m <= limit_dist_m:
        return False
    gap_m = station_dist_m - limit_dist_m
    ctx = BrakePhysicsContext(
        base_decel_ms2=base_decel,
        gradient_pct=gradient_pct,
    )
    decel = decel_for_notch(0.80, base_decel, gradient_pct)
    stop_after_limit = braking_distance_mph(
        limit_mph,
        0.0,
        decel_ms2=decel,
        ctx=ctx,
        apply_margin=False,
    )
    pad_m = brake_reaction_margin_m(limit_mph * MPH_TO_MS)
    return gap_m >= stop_after_limit + pad_m


def should_delay_unified_station_plan(
    *,
    speed_mph: float,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    gradient_pct: float = 0.0,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
) -> bool:
    """
    Dos fases (sí cabe parar tras el cartel): coast a v_límite hasta el
    horizonte de parada. Nunca en parada unificada (gap corto).
    """
    if limit_mph is None or limit_dist_m is None or station_dist_m is None:
        return False
    if not sequential_limit_stop_feasible(
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        base_decel=base_decel,
    ):
        return False
    if speed_mph > limit_mph + 3.0:
        return False
    ctx = BrakePhysicsContext(
        base_decel_ms2=base_decel,
        gradient_pct=gradient_pct,
    )
    horizon = kinematic_horizon_m(
        speed_mph,
        0.0,
        decel_ms2=decel_for_notch(0.80, base_decel, gradient_pct),
        ctx=ctx,
        apply_margin=True,
    )
    return station_dist_m > horizon
