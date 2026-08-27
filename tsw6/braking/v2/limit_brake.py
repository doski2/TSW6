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
    DEFAULT_BRAKE_FILL_S,
    DEFAULT_MAX_BRAKE_DECEL,
    DOWNHILL_LIMIT_GRADIENT_PCT,
    MPH_TO_MS,
    apply_zone_margin_m,
    brake_reaction_margin_m,
    braking_distance_mph,
    is_in_apply_zone,
)
from tsw6.braking.v2.command import (
    LIMIT_COAST_BAND_MPH,
    LIMIT_CONTAIN_ESCALATE_OVER_MPH,
    LIMIT_SCORING_MAX_OVER_MPH,
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
# Distancia al cartel: contención solo en ventana de aplicación (no 60→55 a km).


def _downhill_contain_trigger_over_mph(gradient_pct: float) -> float:
    """Anticipar B1 en bajada: antes si la pendiente es más pronunciada."""
    if gradient_pct <= -1.0:
        return 0.20
    if gradient_pct <= -0.6:
        return 0.28
    return 0.35


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


_PHASE_BY_HANDLE = {3: "B1", 2: "B2", 1: "B3"}
_ONE_STRONGER = {3: 2, 2: 1, 1: 1}
_ONE_WEAKER = {1: 2, 2: 3, 3: 3}


def _service_notch_strength(handle: int) -> int:
    """Mayor = freno más fuerte (B3=3 … B1=1)."""
    return {3: 1, 2: 2, 1: 3}.get(handle, 4)


def _phase_for_handle(handle: int) -> str:
    return _PHASE_BY_HANDLE.get(handle, "B1")


def _apply_notch_hysteresis(
    state: LimitBrakeState,
    *,
    handle: int,
    phase: str,
    dist_start: float,
    apply_now: bool,
    apply_zone_m: float,
    speed_mph: float,
    limit_mph: float,
) -> tuple[int, str]:
    """
    Muesca de menos a más (B1→B2→B3) y de más a menos (B3→B2→B1).
    Un escalón por tick: no saltar a B3 de golpe.
    """
    prev = state.committed_handle
    in_window = apply_now or is_in_apply_zone(dist_start, apply_zone_m)
    if prev is None:
        if in_window:
            start = 3
            state.committed_handle = start
            state.committed_phase = _phase_for_handle(start)
            return start, state.committed_phase
        return handle, phase

    prev_s = _service_notch_strength(prev)
    new_s = _service_notch_strength(handle)
    if new_s > prev_s:
        stepped = _ONE_STRONGER[prev]
        state.committed_handle = stepped
        state.committed_phase = _phase_for_handle(stepped)
        return stepped, state.committed_phase

    if new_s < prev_s:
        at_target = speed_mph <= limit_mph + LIMIT_SCORING_MAX_OVER_MPH
        room_to_weaken = dist_start > apply_zone_m and not apply_now
        if at_target or room_to_weaken:
            stepped = _ONE_WEAKER[prev]
            state.committed_handle = stepped
            state.committed_phase = _phase_for_handle(stepped)
            return stepped, state.committed_phase

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
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
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
        reaction_margin_m=brake_reaction_margin_m(
            speed_ms,
            brake_fill_s=brake_fill_s,
            reaction_base_s=_LIMIT_REACTION_S,
        ),
    )
    state.latch = latch
    state.last_limit_mph = limit_mph
    return latch


def _containment_apply_horizon_m(
    speed_mph: float,
    limit_mph: float,
    gradient_pct: float,
) -> float:
    """
    Distancia al cartel donde ya hay que actuar (B1).

    ``s = (v² − u²) / (2 a_B1)`` más margen de reacción (fill) más zona de
    aplicación (2.5 s de marcha o 12 % del tramo de apply). Misma física que
    el plan de aproximación; no hay tope en metros fijos.
    """
    speed_ms = speed_mph * MPH_TO_MS
    ctx = BrakePhysicsContext(gradient_pct=gradient_pct)
    b1_decel = DEFAULT_MAX_BRAKE_DECEL * _DEFAULT_DECEL_FRAC[3]
    bd = braking_distance_mph(
        speed_mph,
        limit_mph,
        decel_ms2=b1_decel,
        ctx=ctx,
        apply_margin=False,
    )
    if bd != bd or bd == float("inf"):
        return 0.0
    react = brake_reaction_margin_m(speed_ms, reaction_base_s=_LIMIT_REACTION_S)
    apply_at = bd + react
    return apply_at + apply_zone_margin_m(speed_ms, apply_at)


def _try_downhill_containment(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    limit_mph: float,
    distance_m: float,
    gradient_pct: float,
) -> Optional[BrakeTargetResult]:
    """
    Tras el cartel en bajada: coast en neutro; B1 (muesca servicio 1) si repunta.

    Techo operativo limit + 0.9 mph (penalización TSW a +1.0).
    No sustituye el plan de aproximación lejos del cartel.
    """
    if gradient_pct >= DOWNHILL_LIMIT_GRADIENT_PCT:
        return None

    trigger = _downhill_contain_trigger_over_mph(gradient_pct)
    if speed_mph <= limit_mph + trigger:
        return None

    over = speed_mph - limit_mph
    speed_ms = speed_mph * MPH_TO_MS
    if distance_m > _containment_apply_horizon_m(speed_mph, limit_mph, gradient_pct):
        return None

    if over > LIMIT_SCORING_MAX_OVER_MPH + 1.5:
        return None

    # Pasajeros: B1 suele bastar; B2 solo si roza el techo de puntuación.
    if over >= LIMIT_SCORING_MAX_OVER_MPH or over >= LIMIT_CONTAIN_ESCALATE_OVER_MPH:
        handle, phase = 2, "B2"
    else:
        handle, phase = 3, "B1"

    handle, phase = _apply_notch_hysteresis(
        state,
        handle=handle,
        phase=phase,
        dist_start=0.0,
        apply_now=True,
        apply_zone_m=apply_zone_margin_m(speed_ms, distance_m),
        speed_mph=speed_mph,
        limit_mph=limit_mph,
    )

    return BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=distance_m,
        target_speed_mph=limit_mph,
        handle_notch=handle,
        phase=phase,
        dist_start=0.0,
        apply_now=True,
        detail=(
            f"Contención bajada @{limit_mph:.0f} mph "
            f"(techo +{LIMIT_SCORING_MAX_OVER_MPH:.1f})"
        ),
    )


def _refresh_latch_physics(
    latch: LimitBrakeLatch,
    *,
    speed_mph: float,
    gradient_pct: float,
    accel_ms2: Optional[float],
    base_decel: float,
    predict_decel: Optional[PredictDecelFn],
    brake_fill_s: float,
) -> None:
    """Cada tick: a, pendiente y reacción con la velocidad actual (no el primer 55)."""
    latch.gradient_pct = gradient_pct
    latch.accel_ms2 = accel_ms2
    latch.latched_speed_mph = speed_mph
    latch.reaction_margin_m = brake_reaction_margin_m(
        speed_mph * MPH_TO_MS,
        brake_fill_s=brake_fill_s,
        reaction_base_s=_LIMIT_REACTION_S,
    )
    for handle, _ in SERVICE_HANDLES_WEAK_TO_STRONG:
        latch.decel_by_handle[handle] = _decel_for_handle(
            handle, speed_mph, gradient_pct, base_decel, predict_decel)


def _pick_weakest_sufficient_notch(
    *,
    speed_mph: float,
    distance_m: float,
    latch: LimitBrakeLatch,
) -> tuple[int, str, float, bool]:
    """B1→B3: muesca más débil cuya s(perfil)+reacción cabe en la distancia."""
    ctx = BrakePhysicsContext(
        gradient_pct=latch.gradient_pct,
        current_accel_ms2=latch.accel_ms2,
    )
    speed_ms = speed_mph * MPH_TO_MS

    evaluated: list[tuple[int, str, float, float, bool]] = []
    for handle, phase in SERVICE_HANDLES_WEAK_TO_STRONG:
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
        zone = apply_zone_margin_m(speed_ms, apply_at)
        apply_now = is_in_apply_zone(dist_start, zone)
        evaluated.append((handle, phase, dist_start, zone, apply_now))

    if not evaluated:
        return SERVICE_HANDLES_WEAK_TO_STRONG[-1][0], "B3", float("inf"), False

    late = [row for row in evaluated if row[2] < 0]
    if late:
        handle, phase, dist_start, _zone, _apply_now = max(
            late, key=lambda row: _service_notch_strength(row[0]))
        return handle, phase, dist_start, True

    in_zone = [
        row for row in evaluated
        if is_in_apply_zone(row[2], row[3])
    ]
    if in_zone:
        handle, phase, dist_start, _zone, apply_now = in_zone[0]
        return handle, phase, dist_start, apply_now

    handle, phase, dist_start, _zone, _apply_now = evaluated[0]
    return handle, phase, dist_start, False


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
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
) -> Optional[BrakeTargetResult]:
    """
    Planifica frenada al cartel. Re-latch si cambia el límite objetivo.
    """
    if limit_mph is None or distance_m is None or distance_m <= 0:
        state.reset()
        return None
    if speed_mph < limit_mph - 0.5:
        state.reset()
        return None

    contain = _try_downhill_containment(
        state,
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        distance_m=distance_m,
        gradient_pct=gradient_pct,
    )
    if contain is not None:
        return contain

    if speed_mph <= limit_mph + LIMIT_COAST_BAND_MPH:
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
            brake_fill_s=brake_fill_s,
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
            brake_fill_s=brake_fill_s,
        )

    latch = state.latch
    if latch is None:
        return None

    _refresh_latch_physics(
        latch,
        speed_mph=speed_mph,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
        base_decel=base_decel,
        predict_decel=predict_decel,
        brake_fill_s=brake_fill_s,
    )

    handle, phase, dist_start, apply_now = _pick_weakest_sufficient_notch(
        speed_mph=speed_mph,
        distance_m=distance_m,
        latch=latch,
    )
    apply_at = max(0.0, distance_m - dist_start)
    apply_zone_m = apply_zone_margin_m(speed_mph * MPH_TO_MS, apply_at)
    handle, phase = _apply_notch_hysteresis(
        state,
        handle=handle,
        phase=phase,
        dist_start=dist_start,
        apply_now=apply_now,
        apply_zone_m=apply_zone_m,
        speed_mph=speed_mph,
        limit_mph=latch.limit_mph,
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
