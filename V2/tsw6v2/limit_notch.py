"""Escalón B1→B3 y elección de muesca mínima suficiente."""

from __future__ import annotations

from typing import Callable

from tsw6v2.physics import (
    MPH_TO_MS,
    apply_zone_margin_m,
    brake_ctx_for_decel,
    braking_distance_mph,
    coast_trim_covers_overspeed,
    is_downhill_gradient,
    is_in_apply_zone,
    is_sloped_for_coast_trim,
    is_uphill_gradient,
)
from tsw6v2.plan import notch_strength
from tsw6v2.limit_horizon import within_next_brake_horizon
from tsw6v2.planning import is_descending_limit_zone
from tsw6v2.constants import (
    BRAKE_PLAN_LARGE_DROP_MPH,
    LIMIT_CONTAIN_ESCALATE_OVER_MPH,
    LIMIT_DOWNHILL_COAST_TRIM_MPH,
    downhill_ops_coast_ceiling_mph,
)
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


def _in_apply_window(
    *,
    apply_now: bool,
    dist_start: float,
    apply_zone_m: float,
) -> bool:
    return apply_now or is_in_apply_zone(dist_start, apply_zone_m)


def _limit_coast_trim_active(
    *,
    speed_mph: float,
    limit_mph: float,
    distance_m: float,
    gradient_pct: float,
) -> bool:
    """
    ¿Coast + gravedad bastan antes del cartel?

    - Bajada: solo exceso ≤2 mph (gravedad acelera; conservador).
    - Subida: sin tope fijo; ``coast_trim_covers_overspeed`` decide
      (sesión 20260911T201211Z: 57 mph @ +1 %% y 250 m al 50).
    """
    overspeed = speed_mph - limit_mph
    if overspeed <= 0:
        return False
    if is_downhill_gradient(gradient_pct):
        if overspeed > LIMIT_DOWNHILL_COAST_TRIM_MPH:
            return False
    return coast_trim_covers_overspeed(
        speed_mph=speed_mph,
        target_mph=limit_mph,
        distance_m=distance_m,
        gradient_pct=gradient_pct,
    )


def next_brake_overrides_zone_hold(
    *,
    speed_mph: float,
    ops_target_mph: float,
    distance_m: float,
    gradient_pct: float,
    current_posted_mph: float,
    next_posted_mph: float,
) -> bool:
    """
    ¿No diferir el compromiso B1 hacia el cartel siguiente (60→55)?

    Solo lo usa ``downhill_defer_brake_commit`` — **no** la prioridad en
    ``limits.evaluate_limit_brake`` (ahí gana HOLD_DH si ``apply_now`` es false).

    - Dentro del horizonte del next: no diferir.
    - Fuera: banda ``ops_next+2`` … ``ceiling_zona+2`` (p. ej. 56–62.2 mph @ 60
      con techo 60.2 @ −1 %% — sesión 20260908T200808Z).
    - Por encima de ``ceiling+2``: puede diferir; la prioridad devuelve HOLD_DH
      si superas el techo de zona (sesión 20260908T210357Z).
    """
    if not is_downhill_gradient(gradient_pct):
        return False
    if not is_descending_limit_zone(current_posted_mph, next_posted_mph):
        return False
    if within_next_brake_horizon(
        speed_mph=speed_mph,
        next_limit_mph=next_posted_mph,
        next_distance_m=distance_m,
        gradient_pct=gradient_pct,
    ):
        return True
    ceiling = downhill_ops_coast_ceiling_mph(current_posted_mph, gradient_pct)
    if speed_mph <= ops_target_mph + LIMIT_DOWNHILL_COAST_TRIM_MPH:
        return False
    return speed_mph <= ceiling + LIMIT_DOWNHILL_COAST_TRIM_MPH


def _defer_descending_zone_brake(
    *,
    speed_mph: float,
    ops_target_mph: float,
    distance_m: float,
    gradient_pct: float,
    current_posted_mph: float,
    next_posted_mph: float,
) -> bool:
    """
    60→55 lejos: solo diferir si aún vas lento en banda de la zona vigente.

    No diferir si BRAKE_LIMIT al next debe ganar (``next_brake_overrides_zone_hold``).
    """
    if next_brake_overrides_zone_hold(
        speed_mph=speed_mph,
        ops_target_mph=ops_target_mph,
        distance_m=distance_m,
        gradient_pct=gradient_pct,
        current_posted_mph=current_posted_mph,
        next_posted_mph=next_posted_mph,
    ):
        return False
    return speed_mph <= downhill_ops_coast_ceiling_mph(
        current_posted_mph, gradient_pct
    )


def downhill_defer_brake_commit(
    *,
    speed_mph: float,
    ops_target_mph: float,
    distance_m: float,
    gradient_pct: float,
    dist_start: float,
    current_posted_mph: float | None = None,
    next_posted_mph: float | None = None,
) -> bool:
    """
    Pendiente: no comprometer B1 todavía si coast/gravedad bastan.

    - Bajada 60→55 lejos: diferir BRAKE_LIMIT si aún en banda zona vigente.
    - Bajada coast trim: exceso ≤2 mph sobre techo operativo.
    - Subida coast trim: sin tope fijo; decide ``coast_trim_covers_overspeed``.

    Solo aplica antes del primer compromiso de muesca (``committed_handle is None``).
    """
    def _coast_defer() -> bool:
        return _limit_coast_trim_active(
            speed_mph=speed_mph,
            limit_mph=ops_target_mph,
            distance_m=distance_m,
            gradient_pct=gradient_pct,
        )

    # Subida: sin cortar por ds≤0 — ds es margen cinemático, no m al cartel
    # (sesión 20260911T203100Z: ds=-0.7 @ 95 m, coast aún basta).
    if is_uphill_gradient(gradient_pct):
        return _coast_defer()
    if dist_start <= 0:
        return False
    if is_downhill_gradient(gradient_pct):
        if (
            current_posted_mph is not None
            and next_posted_mph is not None
            and is_descending_limit_zone(current_posted_mph, next_posted_mph)
            and _defer_descending_zone_brake(
                speed_mph=speed_mph,
                ops_target_mph=ops_target_mph,
                distance_m=distance_m,
                gradient_pct=gradient_pct,
                current_posted_mph=current_posted_mph,
                next_posted_mph=next_posted_mph,
            )
        ):
            return True
        return _coast_defer()
    return False


def _grade_escalation_allowed(
    gradient_pct: float,
    speed_mph: float,
    limit_mph: float,
) -> bool:
    """En pendiente no subir a B2/B3 hasta ≤2 mph sobre techo operativo."""
    if is_sloped_for_coast_trim(gradient_pct):
        return speed_mph <= limit_mph + LIMIT_DOWNHILL_COAST_TRIM_MPH
    return True


def _step_stronger(
    state: LimitBrakeState,
    prev: int,
    *,
    escalate_cap: Callable[[int, int], int] | None,
) -> tuple[int, str]:
    stepped = _ONE_STRONGER[prev]
    if escalate_cap is not None:
        stepped = escalate_cap(prev, stepped)
    state.committed_handle = stepped
    state.committed_phase = phase_for_handle(stepped)
    state.weak_decel_ticks = 0
    return stepped, state.committed_phase


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
    gradient_pct: float = 0.0,
    defer_commit: bool = False,
    escalate_cap: Callable[[int, int], int] | None = None,
) -> tuple[int, str]:
    """
    Muesca de menos a más (B1→B2→B3) y de más a menos (B3→B2→B1).
    Un escalón por tick: no saltar a B3 de golpe.

    ``defer_commit``: no comprometer B1 (coast trim / zona vigente legal).
    Escalada en pendiente: solo si ``speed ≤ techo_operativo + 2 mph``.
    """
    prev = state.committed_handle
    in_window = _in_apply_window(
        apply_now=apply_now,
        dist_start=dist_start,
        apply_zone_m=apply_zone_m,
    )
    may_escalate = _grade_escalation_allowed(
        gradient_pct, speed_mph, limit_mph
    )
    if prev is None:
        if in_window and not defer_commit:
            start = handle
            state.committed_handle = start
            state.committed_phase = phase_for_handle(start)
            return start, state.committed_phase
        return handle, phase

    prev_s = notch_strength(prev)
    new_s = notch_strength(handle)
    if new_s > prev_s:
        if not may_escalate:
            return prev, state.committed_phase or phase
        return _step_stronger(state, prev, escalate_cap=escalate_cap)

    if new_s < prev_s:
        at_target = speed_mph <= limit_mph + LIMIT_SCORING_MAX_OVER_MPH
        room_to_weaken = dist_start > apply_zone_m and not apply_now
        if at_target or room_to_weaken:
            stepped = _ONE_WEAKER[prev]
            state.committed_handle = stepped
            state.committed_phase = phase_for_handle(stepped)
            state.weak_decel_ticks = 0
            return stepped, state.committed_phase

    if (
        in_window
        and may_escalate
        and speed_mph > limit_mph + LIMIT_CONTAIN_ESCALATE_OVER_MPH
        and prev > 1
    ):
        return _step_stronger(state, prev, escalate_cap=escalate_cap)

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
            apply_margin=False,
        )
        apply_at = bd + latch.reaction_margin_m
        dist_start = distance_m - apply_at
        zone = apply_zone_margin_m(speed_ms, apply_at)
        apply_now = is_in_apply_zone(dist_start, zone)
        evaluated.append((handle, phase, dist_start, zone, apply_now))

    if not evaluated:
        return SERVICE_HANDLES_WEAK_TO_STRONG[-1][0], "B3", float("inf"), False

    in_zone = [
        row for row in evaluated
        if is_in_apply_zone(row[2], row[3])
    ]
    if in_zone:
        speed_drop = speed_mph - latch.limit_mph
        if speed_drop >= BRAKE_PLAN_LARGE_DROP_MPH:
            # 70→45 @ 63 mph: B1 aprendido optimista — mínimo B2 (sesión 183116Z).
            for row in in_zone:
                if row[0] <= 2:
                    handle, phase, dist_start, _zone, apply_now = row
                    return handle, phase, dist_start, apply_now
            for row in evaluated:
                if row[0] == 2 and row[2] >= 0:
                    handle, phase, dist_start, _zone, _apply_now = row
                    return handle, phase, dist_start, True
        handle, phase, dist_start, _zone, apply_now = in_zone[0]
        return handle, phase, dist_start, apply_now

    late = [row for row in evaluated if row[2] < 0]
    if late:
        # Solo si ninguna muesca cabe en ventana: la más fuerte entre las tardías.
        handle, phase, dist_start, _zone, _apply_now = max(
            late, key=lambda row: notch_strength(row[0]))
        return handle, phase, dist_start, True

    handle, phase, dist_start, _zone, _apply_now = evaluated[0]
    return handle, phase, dist_start, False
