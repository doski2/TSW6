"""Fase 5 del tick P1: soltar el freno (un camino por tick) — ``docs/v2/DECISION_MODULOS.md``.

Caminos: bleed de andén, soltar tras bleed, salida lenta, señal heredada (verde / WATCH) y cartel
(``resolve_release_command`` → huérfano). Los mandos de APPLY no viven aquí.
"""

from __future__ import annotations

from typing import Callable, Optional

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import (
    BrakeReleaseState,
    brake_applied_from_probe,
    platform_bleed_brake_command,
    release_brake_command,
    release_service_over_brake_command,
    resolve_orphan_limit_brake_release,
    resolve_release_command,
)
from tsw6v2.decision_types import (
    LimitBrakeDecision,
    TickCtx,
    TickPrep,
    decide_station_neutral_release,
)
from tsw6v2.limits import LimitBrakeState
from tsw6v2.p1_station_gate import (
    DEPARTING_CLEAR_MPH,
    PLATFORM_AT_STOP_M,
    departing_brake_needs_release,
    departing_ipc_release_allowed,
    platform_parked_bleed_release_needed,
    platform_parked_residual_bleed_needed,
    station_coast_release_in_motion,
    station_departure_active,
)
from tsw6v2.service_brake import should_release_over_braked_for_stop_target
from tsw6v2.target import BrakeTargetResult
from tsw6v2.vehicle_adapter import adapter_for_package


def attempt_platform_parked_bleed(
    ctx: TickCtx,
    prep: TickPrep,
    *,
    station_fsm: Optional[str],
    station_dist_m: Optional[float],
    platform_bleed_episode: bool,
    snap: ProbeSnapshot,
) -> Optional[LimitBrakeDecision]:
    """B1 en andén si neutro con cilindros cargados — habilita RELEASE IPC (193606Z)."""
    if not platform_parked_residual_bleed_needed(
        speed_mph=prep.ctx.speed_mph,
        station_dist_m=station_dist_m,
        combined_lever=prep.combined_lever,
        brake_cyl_bar=prep.ctx.cyl,
        station_fsm=station_fsm,
        platform_bleed_episode=platform_bleed_episode,
        snap=snap,
        vehicle_package=ctx.vehicle_package,
    ):
        return None
    cmd = platform_bleed_brake_command(distance_m=station_dist_m)
    return ctx.decide(
        cmd,
        "platform_bleed",
        phase=cmd.phase or "B1",
        detail=cmd.reason,
        handle_notch=cmd.target_notch,
        target_kind="STATION",
    )


def attempt_platform_parked_bleed_release(
    ctx: TickCtx,
    prep: TickPrep,
    *,
    station_fsm: Optional[str],
    station_dist_m: Optional[float],
    platform_bleed_episode: bool,
    platform_bleed_b1_confirmed: bool,
    snap: ProbeSnapshot,
    station_stop_running: bool = False,
    other_target_active: bool = False,
    limit_sign_passed: bool = False,
) -> Optional[LimitBrakeDecision]:
    """RELEASE a neutro tras B1 bleed — sin cartel (195804Z).

    También RELEASE en marcha si la inercia basta para parar en el andén
    (``station_coast_release_in_motion``, sesión 203439Z tick 611).
    """
    # Solo sin otro objetivo activo (cartel/señal/bajada) ni parada en curso
    # (tests 005614, zona 40, downhill hold, señal).
    # Solo con freno aplicado: en neutro/tracción el RELEASE no aporta y pisa la palanca
    # del maquinista en DEPARTING (sesión 201122Z, Crestwood: RELEASE cada 2 ticks).
    in_motion = (
        not station_stop_running
        and not other_target_active
        and limit_sign_passed
        and departing_brake_needs_release(prep.combined_lever)
        and station_coast_release_in_motion(
            speed_mph=prep.ctx.speed_mph,
            station_dist_m=station_dist_m,
            required_decel_ms2=(
                ctx.physics.max_decel_ms2 * ctx.physics.service_decel_frac[3]
            ),
            gradient_pct=float(snap.gradient_pct or 0.0),
        )
    )
    if not in_motion and not platform_parked_bleed_release_needed(
        speed_mph=prep.ctx.speed_mph,
        station_dist_m=station_dist_m,
        combined_lever=prep.combined_lever,
        station_fsm=station_fsm,
        platform_bleed_episode=platform_bleed_episode,
        platform_bleed_b1_confirmed=platform_bleed_b1_confirmed,
        snap=snap,
        vehicle_package=ctx.vehicle_package,
    ):
        return None
    rel = release_brake_command(at_target=True)
    if rel is None:
        return None
    return decide_station_neutral_release(ctx, rel, "platform_bleed_release")


def attempt_departing_brake_release(
    ctx: TickCtx,
    prep: TickPrep,
    *,
    station_fsm: Optional[str],
    station_dist_m: Optional[float] = None,
) -> Optional[LimitBrakeDecision]:
    """Único camino RELEASE en salida lenta (FSM DEPARTING u origen, 223013Z)."""
    if not departing_brake_needs_release(prep.combined_lever):
        return None
    if not station_departure_active(
        speed_mph=prep.ctx.speed_mph,
        station_dist_m=station_dist_m,
        combined_lever=prep.combined_lever,
        station_fsm=station_fsm,
    ):
        return None
    if prep.ctx.speed_mph >= DEPARTING_CLEAR_MPH:
        return None
    if not departing_ipc_release_allowed(
        station_dist_m,
        vehicle_package=ctx.vehicle_package,
    ):
        return None
    rel = release_brake_command(at_target=True)
    if rel is None:
        return None
    return decide_station_neutral_release(ctx, rel, "release")


def attempt_signal_inherited_release(
    ctx: TickCtx,
    prep: TickPrep,
    limit_state: LimitBrakeState,
    snap: ProbeSnapshot,
    *,
    release_ref: BrakeTargetResult,
    reason: str,
) -> Optional[LimitBrakeDecision]:
    """Suelta freno de servicio heredado respecto al plan señal (WATCH o rojo pasado)."""
    if not brake_applied_from_probe(snap, prep.lever, ctx.vehicle_package):
        return None
    pkg = ctx.vehicle_package
    if not adapter_for_package(pkg).analog_lever:
        if not should_release_over_braked_for_stop_target(release_ref, prep.lever):
            return None
    rel = release_service_over_brake_command(reason=reason)
    limit_state.clear_commitment()
    return ctx.decide(
        rel,
        "release",
        phase=rel.phase or "NEU",
        detail=rel.reason,
        handle_notch=rel.target_notch,
        target_kind="SIGNAL",
    )


_SIGNAL_CLEARED_RELEASE_REF = BrakeTargetResult(
    target_kind="SIGNAL",
    distance_m=999.0,
    target_speed_mph=0.0,
    handle_notch=3,
    phase="B1",
    dist_start=500.0,
    apply_now=False,
    detail="",
)


def _station_platform_blocks_signal_cleared_release(
    station_target: Optional[BrakeTargetResult],
) -> bool:
    """Con plan andén en zona de parada: no tratar señal como pasada/verde."""
    if station_target is None:
        return False
    return station_target.distance_m <= PLATFORM_AT_STOP_M


def attempt_p1_releases(
    ctx: TickCtx,
    prep: TickPrep,
    *,
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    snap: ProbeSnapshot,
    target: Optional[BrakeTargetResult],
    station_target: Optional[BrakeTargetResult],
    signal_target: Optional[BrakeTargetResult],
    limit_target: Optional[BrakeTargetResult],
    limit_release_ok: Callable[[Optional[BrakeTargetResult]], bool],
    limit_brake_enabled: bool,
    signal_brake_enabled: bool,
) -> Optional[LimitBrakeDecision]:
    """Señal heredada → cartel; un solo camino de RELEASE por tick."""
    limit_blocks_release = (
        limit_target is not None and limit_target.limit_brake_active
    )
    if signal_brake_enabled and snap.signal_red is False and signal_target is None:
        if (
            not limit_blocks_release
            and brake_applied_from_probe(snap, prep.lever, prep.ctx.vehicle_package)
            and not _station_platform_blocks_signal_cleared_release(station_target)
            and not (station_target is not None and station_target.apply_now)
            and (
                target is None
                or target.target_kind != "STATION"
                or not target.apply_now
            )
            and limit_release_ok(target)
        ):
            cleared = attempt_signal_inherited_release(
                ctx,
                prep,
                limit_state,
                snap,
                release_ref=_SIGNAL_CLEARED_RELEASE_REF,
                reason="Señal pasada/verde: soltar freno heredado",
            )
            if cleared is not None:
                return cleared

    if (
        signal_brake_enabled
        and signal_target is not None
        and not signal_target.apply_now
        and not limit_blocks_release
        and brake_applied_from_probe(snap, prep.lever, prep.ctx.vehicle_package)
        and limit_release_ok(target)
    ):
        released = attempt_signal_inherited_release(
            ctx,
            prep,
            limit_state,
            snap,
            release_ref=signal_target,
            reason="Señal WATCH: reducir freno heredado",
        )
        if released is not None:
            return released

    if limit_release_ok(target):
        return attempt_release(
            prep,
            limit_state=limit_state,
            release_state=release_state,
            snap=snap,
            limit_brake_enabled=limit_brake_enabled,
            limit_target=limit_target if limit_brake_enabled else None,
        )
    return None


def _limit_plan_owns_brake(
    limit_target: Optional[BrakeTargetResult],
    speed_mph: float,
) -> bool:
    """El plan del cartel sigue aplicando y la velocidad no llegó a su objetivo.

    Con el plan en ``apply_now`` el freno es suyo: soltarlo por la banda de ``resolve_release_command``
    (objetivo + 0,4 mph) lo reaplica el tick siguiente (212139Z: 9,26 mph, objetivo 9, cartel 10 a
    139 m, APPLY/RELEASE cada tick durante ~60 s). Soltar queda para cuando el plan deja de aplicar
    o la velocidad alcanza su objetivo.
    """
    return (
        limit_target is not None
        and limit_target.target_kind == "SPEED_LIMIT"
        and limit_target.apply_now
        and not limit_target.downhill_hold
        and speed_mph > limit_target.target_speed_mph
    )


def attempt_release(
    prep: TickPrep,
    *,
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    snap: ProbeSnapshot,
    limit_brake_enabled: bool = True,
    limit_target: Optional[BrakeTargetResult] = None,
) -> Optional[LimitBrakeDecision]:
    if not limit_brake_enabled or not brake_applied_from_probe(
        snap, prep.lever, prep.ctx.vehicle_package
    ):
        return None
    if _limit_plan_owns_brake(limit_target, prep.ctx.speed_mph):
        return None
    release_state.update(prep.ctx.speed_mph, prep.next_limit_mph)
    latch_ops = (
        limit_state.latch.limit_mph if limit_state.latch is not None else None
    )
    rel = resolve_release_command(
        speed_mph=prep.ctx.speed_mph,
        handle_notch=prep.lever,
        effective_limit=prep.ctx.effective,
        next_limit_mph=prep.next_limit_mph,
        distance_next_m=prep.dist_m,
        gradient_pct=prep.ctx.grad,
        latch_ops_target=latch_ops,
        accel_ms2=snap.accel_ms2,
        brake_fill_s=prep.fill_s,
        predict_decel=prep.predict,
    )
    if rel is None:
        latch = limit_state.latch
        committed = (
            latch.limit_mph
            if latch is not None and limit_state.committed_handle is not None
            else None
        )
        rel = resolve_orphan_limit_brake_release(
            speed_mph=prep.ctx.speed_mph,
            handle_notch=prep.lever,
            effective_limit=prep.ctx.effective,
            next_limit_mph=prep.next_limit_mph,
            distance_next_m=prep.dist_m,
            gradient_pct=prep.ctx.grad,
            limit_target=limit_target,
            committed_limit_mph=committed,
        )
    if rel is None:
        return None
    limit_state.clear_commitment()
    if rel.zone_coast_release:
        release_state.latch_after_zone_coast_release(
            prep.ctx.effective,
            prep.ctx.grad,
        )
    elif prep.next_limit_mph is not None:
        release_state.latch(prep.next_limit_mph)
    return prep.ctx.decide(
        rel,
        "release",
        phase=rel.phase or "NEU",
        detail=rel.reason,
        handle_notch=rel.target_notch,
        target_kind="SPEED_LIMIT",
    )
