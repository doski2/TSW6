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
    DEFAULT_BRAKE_FILL_S,
    DEFAULT_MAX_BRAKE_DECEL,
    DOWNHILL_LIMIT_GRADIENT_PCT,
    MPH_TO_MS,
    apply_zone_margin_m,
    brake_ctx_for_decel,
    brake_reaction_margin_m,
    braking_distance_mph,
    is_in_apply_zone,
    kinematic_horizon_m,
)
from tsw6.braking.v2.command import (
    LIMIT_COAST_BAND_MPH,
    LIMIT_CONTAIN_ESCALATE_OVER_MPH,
    LIMIT_SCORING_MAX_OVER_MPH,
    LIMIT_SIGN_PASSED_M,
    SERVICE_HANDLES_WEAK_TO_STRONG,
    BrakeTargetResult,
)
from tsw6.braking.v2.plan import (
    SERVICE_DECEL_FRAC_BY_HANDLE,
    UK_SERVICE_PHASES,
    notch_strength,
    resolve_phase_decel,
)

PredictDecelFn = Callable[[int, float, float], Optional[float]]

_LIMIT_REACTION_S = 1.5
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
    learned_by_handle: dict[int, bool]
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

    prev_s = notch_strength(prev)
    new_s = notch_strength(handle)
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
) -> tuple[float, bool]:
    """(decel m/s², using_learned). Aprendido ya incluye grado."""
    phase = next((p for p in UK_SERVICE_PHASES if p.handle_notch == handle), None)
    if phase is None:
        frac = SERVICE_DECEL_FRAC_BY_HANDLE.get(handle, 0.80)
        return max(base_decel * frac, 0.05), False
    return resolve_phase_decel(
        phase, speed_mph, gradient_pct, base_decel, predict_decel)


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
    learned_by_handle: dict[int, bool] = {}
    for handle, _ in SERVICE_HANDLES_WEAK_TO_STRONG:
        d, learned = _decel_for_handle(
            handle, speed_mph, gradient_pct, base_decel, predict_decel)
        decel_by_handle[handle] = d
        learned_by_handle[handle] = learned

    latch = LimitBrakeLatch(
        limit_mph=limit_mph,
        distance_m=distance_m,
        latched_speed_mph=speed_mph,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
        decel_by_handle=decel_by_handle,
        learned_by_handle=learned_by_handle,
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
    """Misma curva que el plan: ``kinematic_horizon_m`` (s + reacción + zona)."""
    ctx = brake_ctx_for_decel(gradient_pct=gradient_pct, using_learned=False)
    b1_frac = SERVICE_DECEL_FRAC_BY_HANDLE[3]
    horizon = kinematic_horizon_m(
        speed_mph,
        limit_mph,
        decel_ms2=DEFAULT_MAX_BRAKE_DECEL * b1_frac,
        ctx=ctx,
        apply_margin=False,
        reaction_base_s=_LIMIT_REACTION_S,
    )
    return horizon if horizon == horizon else 0.0


def _try_downhill_containment(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    limit_mph: float,
    distance_m: float,
    gradient_pct: float,
    allow_large_over: bool = False,
    force: bool = False,
) -> Optional[BrakeTargetResult]:
    """
    Tras el cartel en bajada: coast en neutro; B1 (muesca servicio 1) si repunta.

    Techo operativo limit + 0.9 mph (penalización TSW a +1.0).
    No sustituye el plan de aproximación lejos del cartel.
    """
    if gradient_pct >= DOWNHILL_LIMIT_GRADIENT_PCT:
        return None

    if not force:
        trigger = _downhill_contain_trigger_over_mph(gradient_pct)
        if speed_mph <= limit_mph + trigger:
            return None

    over = speed_mph - limit_mph
    speed_ms = speed_mph * MPH_TO_MS
    if distance_m > _containment_apply_horizon_m(speed_mph, limit_mph, gradient_pct):
        return None

    if not allow_large_over and over > LIMIT_SCORING_MAX_OVER_MPH + 1.5:
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


def _try_posted_downhill_hold(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    posted_limit_mph: float,
    gradient_pct: float,
) -> Optional[BrakeTargetResult]:
    """Ya en zona: sujetar el límite actual en bajada (no el cartel a 900 m)."""
    return _try_downhill_containment(
        state,
        speed_mph=speed_mph,
        limit_mph=posted_limit_mph,
        distance_m=0.0,
        gradient_pct=gradient_pct,
        allow_large_over=True,
    )


def _try_downhill_approach_hold(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    limit_mph: float,
    distance_m: float,
    gradient_pct: float,
) -> Optional[BrakeTargetResult]:
    """Cartel aún por delante: no soltar si g puede devolver la velocidad."""
    if distance_m <= LIMIT_SIGN_PASSED_M:
        return None
    if speed_mph < limit_mph - 1.0:
        return None
    if speed_mph > limit_mph + LIMIT_SCORING_MAX_OVER_MPH + 1.5:
        return None
    return _try_downhill_containment(
        state,
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        distance_m=distance_m,
        gradient_pct=gradient_pct,
        force=True,
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
        d, learned = _decel_for_handle(
            handle, speed_mph, gradient_pct, base_decel, predict_decel)
        latch.decel_by_handle[handle] = d
        latch.learned_by_handle[handle] = learned


def _pick_weakest_sufficient_notch(
    *,
    speed_mph: float,
    distance_m: float,
    latch: LimitBrakeLatch,
) -> tuple[int, str, float, bool]:
    """B1→B3: muesca más débil cuya s(perfil)+reacción cabe en la distancia."""
    speed_ms = speed_mph * MPH_TO_MS
    evaluated: list[tuple[int, str, float, float, bool]] = []
    for handle, phase in SERVICE_HANDLES_WEAK_TO_STRONG:
        decel = latch.decel_by_handle[handle]
        learned = latch.learned_by_handle.get(handle, False)
        ctx = brake_ctx_for_decel(
            gradient_pct=latch.gradient_pct,
            using_learned=learned,
            current_accel_ms2=latch.accel_ms2,
        )
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
            late, key=lambda row: notch_strength(row[0]))
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
    posted_limit_mph: Optional[float] = None,
) -> Optional[BrakeTargetResult]:
    """
    Planifica frenada al cartel. Re-latch si cambia el límite objetivo.
    """
    posted_hold = None
    if posted_limit_mph is not None:
        posted_hold = _try_posted_downhill_hold(
            state,
            speed_mph=speed_mph,
            posted_limit_mph=posted_limit_mph,
            gradient_pct=gradient_pct,
        )

    next_r: Optional[BrakeTargetResult] = None
    if limit_mph is not None and distance_m is not None and distance_m > 0:
        next_r = _evaluate_next_limit_brake(
            state,
            speed_mph=speed_mph,
            limit_mph=limit_mph,
            distance_m=distance_m,
            gradient_pct=gradient_pct,
            accel_ms2=accel_ms2,
            base_decel=base_decel,
            predict_decel=predict_decel,
            brake_fill_s=brake_fill_s,
        )

    if posted_hold is not None and (
        next_r is None or (not next_r.apply_now and posted_hold.apply_now)
    ):
        return posted_hold
    if next_r is not None:
        return next_r
    return posted_hold


def _evaluate_next_limit_brake(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    limit_mph: float,
    distance_m: float,
    gradient_pct: float,
    accel_ms2: Optional[float],
    base_decel: float,
    predict_decel: Optional[PredictDecelFn],
    brake_fill_s: float,
) -> Optional[BrakeTargetResult]:
    contain = _try_downhill_containment(
        state,
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        distance_m=distance_m,
        gradient_pct=gradient_pct,
    )
    if contain is not None:
        return contain

    hold = _try_downhill_approach_hold(
        state,
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        distance_m=distance_m,
        gradient_pct=gradient_pct,
    )
    if hold is not None:
        return hold

    if speed_mph < limit_mph - 0.5:
        state.reset()
        return None

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
