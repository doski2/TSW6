#!/usr/bin/env python3
"""
limit_brake.py — Frenada por cartel de velocidad (v2).

Al detectar un nuevo límite se **latch**an deceleraciones del perfil, margen de
reacción y gradiente. Cada tick se elige la muesca mínima (B1→B3) cuya
distancia de frenado + margen cabe en la distancia restante.

Ejemplo 60→55 mph: suele bastar B1 (handle 3); en bajada o con inercia → B2/B3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from tsw6.braking.v2.physics import (
    BrakePhysicsContext,
    DEFAULT_MAX_BRAKE_DECEL,
    DOWNHILL_LIMIT_GRADIENT_PCT,
    MPH_TO_MS,
    apply_zone_margin_m,
    braking_distance_mph,
    is_in_apply_zone,
    reaction_margin_m,
)
from tsw6.braking.v2.types import (
    SERVICE_HANDLES_WEAK_TO_STRONG,
    BrakeTargetResult,
)

PredictDecelFn = Callable[[int, float, float], Optional[float]]

# Fracciones servicio Class 323 si no hay perfil
_DEFAULT_DECEL_FRAC = {3: 0.33, 2: 0.55, 1: 0.80}
_LIMIT_REACTION_S = 1.5
_PLANNING_DECEL_AVG_WEIGHT = 0.65


@dataclass
class LimitBrakeLatch:
    """Constantes fijadas al recibir el cartel."""

    limit_mph: float
    distance_m: float
    latched_speed_mph: float
    gradient_pct: float
    accel_ms2: Optional[float]
    decel_by_handle: dict[int, float]
    reaction_margin_m: float


@dataclass
class LimitBrakeState:
    latch: Optional[LimitBrakeLatch] = None
    last_limit_mph: Optional[float] = None
    committed_handle: Optional[int] = None
    committed_phase: Optional[str] = None

    def reset(self) -> None:
        self.latch = None
        self.last_limit_mph = None
        self.committed_handle = None
        self.committed_phase = None


def _service_notch_strength(handle: int) -> int:
    """Mayor = freno más fuerte (B3=3 … B1=1)."""
    return {3: 1, 2: 2, 1: 3}.get(handle, 4)


def _apply_notch_hysteresis(
    state: LimitBrakeState,
    *,
    handle: int,
    phase: str,
    dist_start: float,
    apply_now: bool,
) -> tuple[int, str]:
    """
    Mantiene la muesca comprometida: solo escala a freno más fuerte, no baja B2→B1
    en el mismo cartel (evita baile del mando cerca del límite).
  """
    prev = state.committed_handle
    if prev is None:
        if apply_now or dist_start <= 80.0:
            state.committed_handle = handle
            state.committed_phase = phase
        return handle, phase

    prev_s = _service_notch_strength(prev)
    new_s = _service_notch_strength(handle)
    if new_s > prev_s:
        state.committed_handle = handle
        state.committed_phase = phase
        return handle, phase

    return prev, state.committed_phase or phase


def _decel_for_handle(
    handle: int,
    speed_mph: float,
    gradient_pct: float,
    base_decel: float,
    predict_decel: Optional[PredictDecelFn],
) -> float:
    if predict_decel is not None:
        learned = predict_decel(handle, speed_mph, gradient_pct)
        if learned is not None and learned > 0.05:
            return learned
    frac = _DEFAULT_DECEL_FRAC.get(handle, 0.8)
    grav = 9.80665 * gradient_pct / 100.0
    return max(base_decel * frac + grav, 0.05)


def _limit_changed(
    prev: Optional[float],
    new: float,
    tolerance_mph: float = 2.0,
) -> bool:
    if prev is None:
        return True
    return abs(prev - new) > tolerance_mph


def latch_limit_target(
    state: LimitBrakeState,
    *,
    limit_mph: float,
    distance_m: float,
    speed_mph: float,
    gradient_pct: float,
    accel_ms2: Optional[float],
    base_decel: float,
    predict_decel: Optional[PredictDecelFn],
) -> LimitBrakeLatch:
    speed_ms = speed_mph * MPH_TO_MS
    decel_by_handle: dict[int, float] = {}
    for handle, _ in SERVICE_HANDLES_WEAK_TO_STRONG:
        d = _decel_for_handle(
            handle, speed_mph, gradient_pct, base_decel, predict_decel)
        decel_by_handle[handle] = d

    latch = LimitBrakeLatch(
        limit_mph=limit_mph,
        distance_m=distance_m,
        latched_speed_mph=speed_mph,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
        decel_by_handle=decel_by_handle,
        reaction_margin_m=reaction_margin_m(speed_ms, reaction_time_s=_LIMIT_REACTION_S),
    )
    state.latch = latch
    state.last_limit_mph = limit_mph
    return latch


def _pick_weakest_sufficient_notch(
    *,
    speed_mph: float,
    distance_m: float,
    latch: LimitBrakeLatch,
    downhill: bool,
) -> tuple[int, str, float, bool]:
    """Devuelve (handle, phase, dist_start, apply_now)."""
    ctx = BrakePhysicsContext(
        gradient_pct=latch.gradient_pct,
        current_accel_ms2=latch.accel_ms2,
    )
    best_handle = SERVICE_HANDLES_WEAK_TO_STRONG[-1][0]
    best_phase = SERVICE_HANDLES_WEAK_TO_STRONG[-1][1]
    best_dist_start = float("inf")
    best_apply = False

    handles = list(SERVICE_HANDLES_WEAK_TO_STRONG)
    if downhill:
        handles = list(reversed(handles))

    for handle, phase in handles:
        decel = latch.decel_by_handle[handle]
        bd = braking_distance_mph(
            speed_mph,
            latch.limit_mph,
            decel_ms2=decel,
            ctx=ctx,
            apply_margin=True,
        )
        apply_at = bd + latch.reaction_margin_m
        dist_start = distance_m - apply_at
        zone = apply_zone_margin_m(speed_mph * MPH_TO_MS, apply_at)
        apply_now = is_in_apply_zone(dist_start, zone)

        if dist_start < best_dist_start:
            best_dist_start = dist_start
            best_handle = handle
            best_phase = phase
            best_apply = apply_now

        if downhill and apply_now:
            return handle, phase, dist_start, True
        if not downhill and dist_start <= zone:
            return handle, phase, dist_start, apply_now

    return best_handle, best_phase, best_dist_start, best_apply


def evaluate_limit_brake(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    limit_mph: Optional[float],
    distance_m: Optional[float],
    gradient_pct: float = 0.0,
    accel_ms2: Optional[float] = None,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
    predict_decel: Optional[PredictDecelFn] = None,
) -> Optional[BrakeTargetResult]:
    """
    Planifica frenada al cartel. Re-latch si cambia el límite objetivo.
    """
    if limit_mph is None or distance_m is None or distance_m <= 0:
        state.reset()
        return None
    if limit_mph >= speed_mph - 0.3:
        state.reset()
        return None

    if _limit_changed(state.last_limit_mph, limit_mph):
        latch_limit_target(
            state,
            limit_mph=limit_mph,
            distance_m=distance_m,
            speed_mph=speed_mph,
            gradient_pct=gradient_pct,
            accel_ms2=accel_ms2,
            base_decel=base_decel,
            predict_decel=predict_decel,
        )
    elif state.latch is None:
        latch_limit_target(
            state,
            limit_mph=limit_mph,
            distance_m=distance_m,
            speed_mph=speed_mph,
            gradient_pct=gradient_pct,
            accel_ms2=accel_ms2,
            base_decel=base_decel,
            predict_decel=predict_decel,
        )

    latch = state.latch
    if latch is None:
        return None

    downhill = gradient_pct < DOWNHILL_LIMIT_GRADIENT_PCT
    handle, phase, dist_start, apply_now = _pick_weakest_sufficient_notch(
        speed_mph=speed_mph,
        distance_m=distance_m,
        latch=latch,
        downhill=downhill,
    )
    handle, phase = _apply_notch_hysteresis(
        state,
        handle=handle,
        phase=phase,
        dist_start=dist_start,
        apply_now=apply_now,
    )

    return BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=distance_m,
        target_speed_mph=latch.limit_mph,
        handle_notch=handle,
        phase=phase,
        dist_start=dist_start,
        apply_now=apply_now,
        detail=f"Límite {latch.limit_mph:.0f} mph (latched @{latch.latched_speed_mph:.0f})",
    )
