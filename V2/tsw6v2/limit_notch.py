"""Escalón B1→B3 y elección de muesca mínima suficiente."""

from __future__ import annotations

from typing import Callable

from tsw6v2.physics import (
    MPH_TO_MS,
    apply_zone_margin_m,
    brake_ctx_for_decel,
    braking_distance_mph,
    is_in_apply_zone,
)
from tsw6v2.plan import notch_strength
from tsw6v2.target import (
    LIMIT_SCORING_MAX_OVER_MPH,
    SERVICE_HANDLES_WEAK_TO_STRONG,
)
from tsw6v2.limit_state import LimitBrakeLatch, LimitBrakeState

_PHASE_BY_HANDLE = {3: "B1", 2: "B2", 1: "B3"}
_ONE_STRONGER = {3: 2, 2: 1, 1: 1}
_ONE_WEAKER = {1: 2, 2: 3, 3: 3}


def phase_for_handle(handle: int) -> str:
    return _PHASE_BY_HANDLE.get(handle, "B1")


def apply_notch_hysteresis(
    state: LimitBrakeState,
    *,
    handle: int,
    phase: str,
    dist_start: float,
    apply_now: bool,
    apply_zone_m: float,
    speed_mph: float,
    limit_mph: float,
    escalate_cap: Callable[[int, int], int] | None = None,
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
            state.committed_phase = phase_for_handle(start)
            return start, state.committed_phase
        return handle, phase

    prev_s = notch_strength(prev)
    new_s = notch_strength(handle)
    if new_s > prev_s:
        stepped = _ONE_STRONGER[prev]
        if escalate_cap is not None:
            stepped = escalate_cap(prev, stepped)
        state.committed_handle = stepped
        state.committed_phase = phase_for_handle(stepped)
        return stepped, state.committed_phase

    if new_s < prev_s:
        at_target = speed_mph <= limit_mph + LIMIT_SCORING_MAX_OVER_MPH
        room_to_weaken = dist_start > apply_zone_m and not apply_now
        if at_target or room_to_weaken:
            stepped = _ONE_WEAKER[prev]
            state.committed_handle = stepped
            state.committed_phase = phase_for_handle(stepped)
            return stepped, state.committed_phase

    return prev, state.committed_phase or phase


def pick_weakest_sufficient_notch(
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
