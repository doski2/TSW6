#!/usr/bin/env python3
"""
priority.py — Prioridad entre objetivos (v2, orientado a vía real).

Reglas:
1. Filtrar objetivos que no compiten (cartel absorbido por estación, señal detrás del andén).
2. Elegir por distancia en vía (lo que viene antes) y dist_start (tiempo a frenar).
3. Desempate por tipo solo si dist_start está empatado (±5 m).
"""

from __future__ import annotations

from typing import Optional

from tsw6.braking.v2.cluster import (
    is_unified_limit_station_stop,
    should_delay_unified_station_plan,
    targets_are_clustered,
)
from tsw6.braking.v2.physics import TARGET_CLUSTER_GAP_M
from tsw6.braking.v2.types import BrakeTargetKind, BrakeTargetResult

_URGENCY_TIE_M = 5.0
_SIGNAL_BEHIND_STATION_M = 50.0  # señal «un poco después» del andén
_LIMIT_SPEED_MARGIN_MPH = 0.9
_KIND_PRIORITY: dict[BrakeTargetKind, int] = {
    "SIGNAL": 0,
    "SPEED_LIMIT": 1,
    "STATION": 2,
}


def limit_redundant_for_station(
    *,
    speed_mph: float,
    limit_mph: float,
    limit_dist_m: float,
    station_dist_m: float,
    gradient_pct: float = 0.0,
) -> bool:
    """
    True si no hace falta un plan de cartel aparte: la parada en andén basta.

    - Ya vas a velocidad del cartel (o menos).
    - Parada unificada: no cabe 60→55 soltar y luego parar → estación frena sola.
    """
    if not targets_are_clustered(limit_dist_m, station_dist_m):
        return False
    if limit_dist_m > station_dist_m:
        return False
    if speed_mph > limit_mph + _LIMIT_SPEED_MARGIN_MPH:
        return False
    return not should_delay_unified_station_plan(
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
    )


def signal_behind_station(
    signal_dist_m: float,
    station_dist_m: float,
    margin_m: float = _SIGNAL_BEHIND_STATION_M,
) -> bool:
    """Señal un poco después del andén — priorizar parada."""
    if signal_dist_m <= station_dist_m:
        return False
    gap = signal_dist_m - station_dist_m
    return gap <= margin_m or targets_are_clustered(signal_dist_m, station_dist_m)


def station_plan_actionable(
    pool: list[BrakeTargetResult],
    *,
    speed_mph: float = 0.0,
) -> bool:
    """True si el paso de estación ya venció (no la ventana gorda de B1)."""
    del speed_mph
    for c in pool:
        if c.target_kind != "STATION":
            continue
        if c.dist_start <= 0:
            return True
    return False


def should_prefer_signal_over_limit(
    signal_dist_m: float,
    limit_dist_m: float,
    gap_m: float = TARGET_CLUSTER_GAP_M,
) -> bool:
    """Señal en el mismo bloque y no detrás del cartel."""
    return (
        signal_dist_m <= limit_dist_m + gap_m
        and signal_dist_m <= limit_dist_m + 80.0
    )


def _filter_pool(
    pool: list[BrakeTargetResult],
    *,
    speed_mph: float,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    signal_dist_m: Optional[float],
    gradient_pct: float,
) -> list[BrakeTargetResult]:
    out = list(pool)

    # Cartel antes del andén: ¿hace falta plan de límite aparte?
    if (
        limit_mph is not None
        and limit_dist_m is not None
        and station_dist_m is not None
        and limit_dist_m > 0
        and station_dist_m > 0
        and limit_dist_m <= station_dist_m
        and targets_are_clustered(limit_dist_m, station_dist_m)
    ):
        actionable_station = station_plan_actionable(out, speed_mph=speed_mph)
        unified = is_unified_limit_station_stop(
            limit_mph=limit_mph,
            limit_dist_m=limit_dist_m,
            station_dist_m=station_dist_m,
            gradient_pct=gradient_pct,
        )
        redundant_limit = limit_redundant_for_station(
            speed_mph=speed_mph,
            limit_mph=limit_mph,
            limit_dist_m=limit_dist_m,
            station_dist_m=station_dist_m,
            gradient_pct=gradient_pct,
        )
        if unified:
            # Mientras el cartel sigue por delante, el 55 marca el APPLY.
            # dist_start de estación es negativo desde 800 m (B1) y no debe ganar.
            if limit_dist_m <= 8.0:
                out = [c for c in out if c.target_kind != "SPEED_LIMIT"]
        elif speed_mph > limit_mph + _LIMIT_SPEED_MARGIN_MPH:
            # Dos fases: cartel primero si aún por encima del límite.
            out = [c for c in out if c.target_kind != "STATION"]
        elif redundant_limit and actionable_station:
            out = [c for c in out if c.target_kind != "SPEED_LIMIT"]

    # Señal detrás del andén → estación
    if (
        signal_dist_m is not None
        and station_dist_m is not None
        and signal_behind_station(signal_dist_m, station_dist_m)
        and any(c.target_kind == "STATION" for c in out)
    ):
        out = [c for c in out if c.target_kind != "SIGNAL"]

    # Señal delante del cartel en el mismo bloque → señal sobre límite
    if (
        signal_dist_m is not None
        and limit_dist_m is not None
        and any(c.target_kind == "SIGNAL" for c in out)
        and any(c.target_kind == "SPEED_LIMIT" for c in out)
        and should_prefer_signal_over_limit(signal_dist_m, limit_dist_m)
    ):
        out = [c for c in out if c.target_kind != "SPEED_LIMIT"]

    return out


def select_urgent_target(
    candidates: list[BrakeTargetResult],
    *,
    speed_mph: float = 0.0,
    limit_mph: Optional[float] = None,
    limit_dist_m: Optional[float] = None,
    station_dist_m: Optional[float] = None,
    signal_dist_m: Optional[float] = None,
    gradient_pct: float = 0.0,
) -> Optional[BrakeTargetResult]:
    if not candidates:
        return None

    pool = _filter_pool(
        candidates,
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        signal_dist_m=signal_dist_m,
        gradient_pct=gradient_pct,
    )
    if not pool:
        return None

    def sort_key(c: BrakeTargetResult) -> tuple[float, float, int]:
        # 1. Lo que viene antes en vía  2. Tiempo a frenar  3. Tipo
        return (c.distance_m, c.urgency, _KIND_PRIORITY[c.target_kind])

    pool.sort(key=sort_key)
    best = pool[0]
    for other in pool[1:]:
        if sort_key(other)[0] > best.distance_m + _URGENCY_TIE_M:
            break
        if abs(other.urgency - best.urgency) > _URGENCY_TIE_M:
            continue
        if sort_key(other) < sort_key(best):
            best = other
    return best
