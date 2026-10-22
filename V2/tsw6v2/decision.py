"""Un tick P1: cartel + andén + RELEASE/COAST."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Optional

from tsw6v2.plan import PredictDecelFn
from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import (
    BrakeCommand,
    BrakeReleaseState,
    brake_applied_from_probe,
    platform_bleed_brake_command,
    release_brake_command,
    release_service_over_brake_command,
    resolve_orphan_limit_brake_release,
    resolve_release_command,
)
from tsw6v2.vehicle_adapter import adapter_for_package
from tsw6v2.vehicle_package import (
    mc_click_hysteresis_m,
    mc_click_wait,
    mc_limit_brake_fraction,
    mc_stop_brake_fraction,
)
from tsw6v2.decision_prep import brake_applied, brake_kind, prepare_tick
from tsw6v2.decision_types import LimitBrakeDecision, TickCtx, TickPrep
from tsw6v2.p1_station_gate import (
    station_coast_release_in_motion,
    DEPARTING_CLEAR_MPH,
    PLATFORM_AT_STOP_M,
    departing_brake_needs_release,
    departing_ipc_release_allowed,
    departure_limit_target_or_coast,
    platform_parked_bleed_release_needed,
    platform_parked_residual_bleed_needed,
    should_skip_p1_release,
    station_departure_active,
)
from tsw6v2.service_brake import should_release_over_braked_for_stop_target
from tsw6v2 import diag_station  # DIAG_STATION_TEMPORAL: quitar tras 212814Z
from tsw6v2.constants import LIMIT_SIGN_PASSED_M, NEUTRAL_NOTCH
from tsw6v2.learner import LearnerProfile
from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake
from tsw6v2.p1_emergency import EmergencyTargetKind, check_p1_emergency
from tsw6v2.p1_policy import (
    limit_release_allowed,
    pick_p1_brake_target,
    should_allow_station_watch_when_deferred,
)
from tsw6v2.station_plan import (
    DEFAULT_STATION_CFG,
    STATION_SCHEDULE_SLACK_ENABLED,
    should_suppress_station_braking_for_departure,
    station_within_dwell_zone,
)
from tsw6v2.signal_brake import evaluate_signal_brake
from tsw6v2.signal_plan import (
    should_suppress_signal_braking_for_departure,
    signal_in_play,
)
from tsw6v2.station_brake import (
    evaluate_station_brake,
    station_distance_for_brake_plan,
)
from tsw6v2.target import BrakeTargetResult


def _overlay_active_zone_hold(
    pick: Optional[BrakeTargetResult],
    limit_target: Optional[BrakeTargetResult],
) -> Optional[BrakeTargetResult]:
    """
    HOLD_DH activo manda aunque el pick sea STATION/SIGNAL WATCH (173809Z).

    ``p1tgt`` sigue siendo el pick; el mando usa contención de zona.
    """
    if (
        limit_target is None
        or not limit_target.apply_now
        or not limit_target.downhill_hold
    ):
        return pick
    if pick is None:
        return limit_target
    if pick.target_kind == "SPEED_LIMIT" and pick.apply_now:
        return pick
    if pick.target_kind in ("STATION", "SIGNAL") and not pick.apply_now:
        return limit_target
    return pick


def _air_apply_block(
    learner: Optional[LearnerProfile],
    cmd: BrakeCommand,
    cyl: Optional[float],
    lever: int,
) -> Optional[tuple[str, str]]:
    if learner is None or cmd.kind != "APPLY":
        return None
    if cmd.target_fraction is not None:
        return None
    if cmd.target_notch is not None and int(cmd.target_notch) == int(lever):
        return None
    if learner.inhibit_reapply(cyl):
        return ("air_recharge", "Esperar recarga aire tras soltar")
    if not learner.air_ready(cyl, lever=lever):
        return ("air_fill", "Esperando presión cilindro")
    return None


def _plan_reason(cmd: BrakeCommand, target: BrakeTargetResult) -> str:
    if cmd.kind == "RELEASE":
        return "release"
    if cmd.kind == "COAST_THROTTLE":
        return "coast_throttle"
    if target.downhill_hold and cmd.kind == "APPLY":
        return "downhill_hold"
    return "plan"


def _attempt_platform_parked_bleed(
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


def _decide_station_neutral_release(
    ctx: TickCtx,
    rel: BrakeCommand,
    reason: str,
) -> LimitBrakeDecision:
    return ctx.decide(
        rel,
        reason,
        phase=rel.phase or "NEU",
        detail=rel.reason,
        handle_notch=rel.target_notch,
        target_kind="STATION",
    )


def _attempt_platform_parked_bleed_release(
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
    return _decide_station_neutral_release(ctx, rel, "platform_bleed_release")


def _attempt_departing_brake_release(
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
    return _decide_station_neutral_release(ctx, rel, "release")


def _attempt_signal_inherited_release(
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


def _attempt_p1_releases(
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
            cleared = _attempt_signal_inherited_release(
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
        released = _attempt_signal_inherited_release(
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
        return _attempt_release(
            prep,
            limit_state=limit_state,
            release_state=release_state,
            snap=snap,
            limit_brake_enabled=limit_brake_enabled,
            limit_target=limit_target if limit_brake_enabled else None,
        )
    return None


def _signal_distance_m(snap: ProbeSnapshot) -> Optional[float]:
    if snap.signal_red is not True or snap.signal_dist_cm is None:
        return None
    dist = float(snap.signal_dist_cm) / 100.0
    return dist if dist > 0 else None


def _decision_from_emergency(
    prep: TickPrep,
    cmd: BrakeCommand,
    *,
    target_kind: EmergencyTargetKind,
    distance_m: float,
) -> LimitBrakeDecision:
    station_dist = distance_m if target_kind == "STATION" else None
    return prep.ctx.decide(
        cmd,
        "emergency",
        phase=cmd.phase or "B3",
        dist_start_m=distance_m,
        apply_now=True,
        detail=cmd.reason,
        handle_notch=cmd.target_notch,
        target_kind=target_kind,
        station_dist_m=station_dist,
    )


def _station_emergency_suppressed(
    *,
    speed_mph: float,
    station_distance_m: float,
    throttle_notch: int,
    station_fsm: Optional[str] = None,
) -> bool:
    """Salida en marcha: no emergencia andén a velocidad de arranque."""
    if station_fsm == "DEPARTING":
        from tsw6v2.station_plan import is_departure_creep_context

        if is_departure_creep_context(
            station_distance_m,
            speed_mph,
            station_fsm=station_fsm,
        ):
            return True
    if not should_suppress_station_braking_for_departure(
        speed_mph=speed_mph,
        station_distance_m=station_distance_m,
        throttle_notch=throttle_notch,
    ):
        return False
    cap = DEFAULT_STATION_CFG.departure_speed_mph * 1.35
    return speed_mph <= cap


def _signal_emergency_suppressed(
    *,
    speed_mph: float,
    signal_distance_m: float,
    throttle_notch: int,
    station_distance_m: Optional[float] = None,
) -> bool:
    """Misma ventana que el plan gradual: rojo de salida con tracción lenta."""
    return should_suppress_signal_braking_for_departure(
        speed_mph=speed_mph,
        signal_distance_m=signal_distance_m,
        throttle_notch=throttle_notch,
        station_distance_m=station_distance_m,
    )


def _attempt_p1_emergency(
    prep: TickPrep,
    snap: ProbeSnapshot,
    *,
    station_distance_m: Optional[float] = None,
    station_fsm: Optional[str] = None,
) -> Optional[LimitBrakeDecision]:
    signal_dist = _signal_distance_m(snap)
    checks: list[tuple[EmergencyTargetKind, float]] = []
    if (
        signal_dist is not None
        and signal_in_play(
            signal_dist_m=signal_dist,
            station_dist_m=station_distance_m,
        )
    ):
        checks.append(("SIGNAL", signal_dist))
    if station_distance_m is not None:
        emerg_stn = station_distance_for_brake_plan(
            station_distance_m,
            prep.ctx.speed_mph,
        )
        if emerg_stn is not None:
            checks.append(("STATION", emerg_stn))
    throttle = prep.throttle_notch
    for kind, dist in checks:
        if (
            kind == "SIGNAL"
            and _signal_emergency_suppressed(
                speed_mph=prep.ctx.speed_mph,
                signal_distance_m=dist,
                throttle_notch=throttle,
                station_distance_m=station_distance_m,
            )
        ):
            continue
        if (
            kind == "STATION"
            and _station_emergency_suppressed(
                speed_mph=prep.ctx.speed_mph,
                station_distance_m=dist,
                throttle_notch=throttle,
                station_fsm=station_fsm,
            )
        ):
            continue
        cmd = check_p1_emergency(
            target_kind=kind,
            speed_mph=prep.ctx.speed_mph,
            urgent_dist_m=dist,
            gradient_pct=prep.ctx.grad,
            brake_transition_s=prep.fill_s,
            accel_ms2=snap.accel_ms2,
        )
        if cmd is not None:
            return _decision_from_emergency(prep, cmd, target_kind=kind, distance_m=dist)
    return None


def _attempt_release(
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


def _station_stop_continues(
    limit_state: LimitBrakeState,
    station_dist_m: Optional[float],
    speed_mph: float,
) -> bool:
    """Parada MC ya empezada: no soltar a neutro ni dejar la palanca clavada (005614Z)."""
    anchor = limit_state.station_stop_m
    if anchor is None or station_dist_m is None:
        return False
    if station_dist_m > anchor + 20.0:
        return False
    return speed_mph > 1.0


def _mc_station_fraction_command(
    ctx: TickCtx,
    distance_m: float,
) -> Optional[BrakeCommand]:
    frac = mc_stop_brake_fraction(
        ctx.vehicle_package,
        speed_mph=ctx.speed_mph,
        distance_m=distance_m,
        gradient_pct=ctx.grad,
        decel_table=ctx.mc_decel_table,
    )
    if frac is None:
        return None
    return BrakeCommand(
        kind="APPLY",
        target_fraction=frac,
        target_notch=None,
        phase=f"{frac:.3f}",
        reason=f"Estación dist={distance_m:.0f}m",
        distance_m=distance_m,
    )


def _mc_station_roll_wanted(
    ctx: TickCtx,
    limit_state: LimitBrakeState,
    distance_m: float,
    *,
    running: bool,
) -> bool:
    """¿Rodar en neutro hasta el clic? Misma regla para el plan y para ``_continue_station_stop``."""
    return mc_click_wait(
        ctx.vehicle_package,
        speed_mph=ctx.speed_mph,
        distance_m=distance_m,
        gradient_pct=ctx.grad,
        click_decel_ms2=ctx.click_decel_ms2,
        extra_margin_m=mc_click_hysteresis_m(distance_m, stop_running=running),
        latch=limit_state.roll_latch_for(running),
    )


def _continue_station_stop(
    ctx: TickCtx,
    limit_state: LimitBrakeState,
    target: Optional[BrakeTargetResult],
    station_dist_m: Optional[float] = None,
) -> Optional[LimitBrakeDecision]:
    dist = station_dist_m
    if dist is None and target is not None and target.target_kind == "STATION":
        dist = target.distance_m
    if dist is None or not _station_stop_continues(limit_state, dist, ctx.speed_mph):
        return None
    if not adapter_for_package(ctx.vehicle_package).analog_lever:
        return None
    if _mc_station_roll_wanted(ctx, limit_state, dist, running=True):
        rel = BrakeCommand(
            kind="RELEASE",
            target_notch=NEUTRAL_NOTCH,
            phase="NEU",
            reason="Andén: rodar hasta el clic",
            distance_m=dist,
        )
        return _decide_station_neutral_release(ctx, rel, "station_roll")
    cmd = _mc_station_fraction_command(ctx, dist)
    if cmd is None:
        return None
    return ctx.decide(
        cmd,
        "plan",
        phase=cmd.phase or "",
        detail=cmd.reason,
        apply_now=True,
        target_kind="STATION",
        station_dist_m=dist,
    )


def _mc_station_stop_fraction(
    cmd: Optional[BrakeCommand],
    target: BrakeTargetResult,
    ctx: TickCtx,
    limit_state: LimitBrakeState,
) -> Optional[BrakeCommand]:
    """Andén MC: fracción nueva cada tick. El snap evita el hueco 0,64–0,72."""
    if cmd is None or cmd.kind != "APPLY" or target.target_kind != "STATION":
        return cmd
    if "puertas" in (cmd.reason or ""):
        return cmd
    if not adapter_for_package(ctx.vehicle_package).analog_lever:
        return cmd
    # Histéresis: con la parada ya en curso (clic aplicado) no volver a rodar (oscilación).
    running = _station_stop_continues(limit_state, target.distance_m, ctx.speed_mph)
    if _mc_station_roll_wanted(ctx, limit_state, target.distance_m, running=running):
        # Rodar en neutro: el clic 0,64 frenaría de más a esta distancia (011059Z).
        return BrakeCommand(
            kind="RELEASE",
            target_notch=NEUTRAL_NOTCH,
            phase="NEU",
            reason="Andén: rodar hasta el clic",
            distance_m=target.distance_m,
        )
    frac_cmd = _mc_station_fraction_command(ctx, target.distance_m)
    if frac_cmd is None:
        return cmd
    limit_state.station_stop_m = target.distance_m
    return frac_cmd


def _mc_limit_fraction(
    cmd: Optional[BrakeCommand],
    target: BrakeTargetResult,
    ctx: TickCtx,
    limit_state: LimitBrakeState,
) -> Optional[BrakeCommand]:
    """Cartel MC: posición del eje según la decel necesaria, no el peldaño B1/B2/B3 (212139Z)."""
    if cmd is None or cmd.kind != "APPLY" or target.target_kind != "SPEED_LIMIT":
        return cmd
    if not adapter_for_package(ctx.vehicle_package).analog_lever:
        return cmd
    latch = limit_state.latch
    reaction_m = latch.reaction_margin_m if latch is not None else 0.0
    frac = mc_limit_brake_fraction(
        ctx.vehicle_package,
        speed_mph=ctx.speed_mph,
        target_mph=target.target_speed_mph,
        distance_m=max(0.0, target.distance_m - reaction_m),
        gradient_pct=ctx.grad,
        decel_table=ctx.mc_decel_table,
    )
    if frac is None:
        return cmd
    return replace(
        cmd,
        target_fraction=frac,
        phase=f"{frac:.3f}",
    )


def _finalize_target_decision(
    ctx: TickCtx,
    target: BrakeTargetResult,
    *,
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    snap: ProbeSnapshot,
    learner: Optional[LearnerProfile],
    lever: int,
    throttle_notch: int,
    dist_m: Optional[float],
    next_limit_mph: Optional[float],
    grad: float,
) -> LimitBrakeDecision:
    """Convierte ``BrakeTargetResult`` ganador en ``LimitBrakeDecision``."""
    if target.target_kind == "SPEED_LIMIT" and release_state.should_inhibit_limit_rebrake(
        speed_mph=ctx.speed_mph,
        next_limit_mph=next_limit_mph,
        handle_notch=lever,
        plan=None,
        gradient_pct=grad,
        distance_next_m=dist_m,
        effective_limit=ctx.effective,
    ):
        return ctx.idle("coast_latch", target=target)

    cmd = target.to_brake_command(
        throttle_notch=throttle_notch,
        current_notch=lever,
        speed_mph=ctx.speed_mph,
        gradient_pct=grad,
        brake_committed=(
            limit_state.committed_handle is not None
            if target.target_kind == "SPEED_LIMIT"
            else False
        ),
    )
    cmd = _mc_station_stop_fraction(cmd, target, ctx, limit_state)
    cmd = _mc_limit_fraction(cmd, target, ctx, limit_state)

    if cmd is None or (cmd.kind == "APPLY" and not target.apply_now):
        continued = _continue_station_stop(ctx, limit_state, target)
        if continued is not None:
            return continued
        if cmd is None:
            return ctx.idle("command_none", target=target)
        return ctx.idle("apply_deferred", target=target)

    air_block = _air_apply_block(learner, cmd, ctx.cyl, lever)
    if air_block is not None:
        reason, detail = air_block
        return ctx.idle(reason, target=target, detail=detail)

    decision = ctx.from_target(cmd, target, _plan_reason(cmd, target))
    if (
        cmd.target_notch is None
        and cmd.target_fraction is not None
        and target.target_kind == "STATION"
    ):
        decision.phase = cmd.phase or ""
        decision.handle_notch = None
    decision.target_kind = target.target_kind
    decision.station_dist_m = (
        target.distance_m if target.target_kind == "STATION" else None
    )
    return decision


def evaluate_p1_tick(
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    snap: ProbeSnapshot,
    *,
    learner: Optional[LearnerProfile] = None,
    predict_decel: Optional[PredictDecelFn] = None,
    station_distance_m: Optional[float] = None,
    station_eta: Optional[str] = None,
    schedule_slack_enabled: bool = STATION_SCHEDULE_SLACK_ENABLED,
    limit_brake_enabled: bool = True,
    station_brake_enabled: bool = True,
    signal_brake_enabled: bool = True,
    station_fsm: Optional[str] = None,
    platform_bleed_episode: bool = False,
    platform_bleed_b1_confirmed: bool = False,
) -> LimitBrakeDecision:
    """Cartel + andén + señal → un ``BrakeCommand`` o sin mando."""
    if not limit_brake_enabled and not station_brake_enabled and not signal_brake_enabled:
        return LimitBrakeDecision.idle(reason="p1_off")

    station_dist_geo: Optional[float] = None
    if station_distance_m is not None and station_distance_m > 0:
        station_dist_geo = float(station_distance_m)
    # ``station_dist``: plan STATION; ``station_dist_geo``: señal/release/FSM geometría.
    station_dist: Optional[float] = (
        station_dist_geo if station_brake_enabled else None
    )

    prep = prepare_tick(snap, learner, predict_decel)
    if prep is None:
        return LimitBrakeDecision.idle(reason="no_speed")

    emerg = _attempt_p1_emergency(
        prep,
        snap,
        station_distance_m=station_dist_geo,
        station_fsm=station_fsm,
    )
    if emerg is not None:
        return emerg

    ctx = prep.ctx
    limit_target: Optional[BrakeTargetResult] = None
    posted = ctx.effective if snap.speed_limit_ms else None
    if limit_brake_enabled and (
        (prep.next_limit_mph is not None and prep.dist_m is not None)
        or posted is not None
    ):
        limit_target = evaluate_limit_brake(
            limit_state,
            speed_mph=ctx.speed_mph,
            limit_mph=prep.next_limit_mph,
            distance_m=prep.dist_m,
            gradient_pct=ctx.grad,
            accel_ms2=snap.accel_ms2,
            predict_decel=prep.predict,
            posted_limit_mph=posted,
            brake_fill_s=prep.fill_s,
            escalate_cap=prep.escalate_cap,
            learner=learner,
            lever=prep.lever,
            brake_cyl_bar=ctx.cyl,
            release_state=release_state,
            brake_kind=brake_kind(snap.train_brake, snap.dyn_brake),
            brake_applied=brake_applied(snap.train_brake, snap.dyn_brake),
            base_decel=ctx.physics.max_decel_ms2,
        )
        limit_target = departure_limit_target_or_coast(
            limit_target,
            limit_state,
            speed_mph=ctx.speed_mph,
            station_dist_m=station_dist_geo,
            combined_lever=prep.combined_lever,
            station_fsm=station_fsm,
            posted_limit_mph=posted,
            gradient_pct=ctx.grad,
            next_limit_mph=prep.next_limit_mph,
            next_distance_m=prep.dist_m,
        )

    station_target: Optional[BrakeTargetResult] = None
    station_plan_dist = station_distance_for_brake_plan(station_dist, ctx.speed_mph)
    if station_plan_dist is not None:
        station_allow_watch = should_allow_station_watch_when_deferred(
            speed_mph=ctx.speed_mph,
            station_dist_m=station_plan_dist,
            limit_mph=prep.next_limit_mph,
            limit_dist_m=prep.dist_m,
            gradient_pct=ctx.grad,
            brake_fill_s=prep.fill_s,
            accel_ms2=snap.accel_ms2,
        ) or station_within_dwell_zone(station_plan_dist)
        station_target = evaluate_station_brake(
            speed_mph=ctx.speed_mph,
            station_distance_m=station_plan_dist,
            gradient_pct=ctx.grad,
            predict_decel=prep.predict,
            throttle_notch=prep.throttle_notch,
            station_eta=station_eta,
            schedule_slack_enabled=schedule_slack_enabled,
            brake_fill_s=prep.fill_s,
            base_decel=ctx.physics.max_decel_ms2,
            allow_watch=station_allow_watch,
            plan_decel_ms2=ctx.physics.station_plan_decel_ms2,
        )
        # DIAG_STATION_TEMPORAL: quitar tras investigación 212814Z.
        diag_station.log_station_tick(
            tick_ctx=ctx,
            station_plan_dist=station_plan_dist,
            station_eta=station_eta,
            station_allow_watch=station_allow_watch,
            throttle_notch=prep.throttle_notch,
            station_target=station_target,
            predict_decel=prep.predict,
            brake_fill_s=prep.fill_s,
            base_decel=ctx.physics.max_decel_ms2,
            plan_decel_ms2=ctx.physics.station_plan_decel_ms2,
        )
        if (
            learner is not None
            and station_target is not None
            and station_target.apply_now
            and station_target.handle_notch in (1, 2, 3)
        ):
            learner.observe_brake_decel(
                handle=station_target.handle_notch,
                speed_mph=ctx.speed_mph,
                gradient_pct=ctx.grad,
                accel_ms2=snap.accel_ms2,
                lever=prep.lever,
                brake_cyl_bar=ctx.cyl,
                brake_kind=brake_kind(snap.train_brake, snap.dyn_brake),
                brake_applied=brake_applied(snap.train_brake, snap.dyn_brake),
            )

    signal_dist = _signal_distance_m(snap)
    signal_target: Optional[BrakeTargetResult] = None
    if (
        signal_brake_enabled
        and signal_in_play(
            signal_dist_m=signal_dist,
            station_dist_m=station_dist_geo,
        )
    ):
        signal_target = evaluate_signal_brake(
            speed_mph=ctx.speed_mph,
            signal_distance_m=signal_dist,
            gradient_pct=ctx.grad,
            predict_decel=prep.predict,
            throttle_notch=prep.throttle_notch,
            station_distance_m=station_dist_geo,
            brake_fill_s=prep.fill_s,
            base_decel=ctx.physics.max_decel_ms2,
        )

    target = pick_p1_brake_target(
        speed_mph=ctx.speed_mph,
        limit_target=limit_target if limit_brake_enabled else None,
        station_target=station_target,
        signal_target=signal_target,
        signal_dist_m=signal_dist,
        limit_mph=prep.next_limit_mph,
        limit_dist_m=prep.dist_m,
        station_dist_m=station_dist_geo,
        effective_limit=ctx.effective,
        gradient_pct=ctx.grad,
        brake_fill_s=prep.fill_s,
        accel_ms2=snap.accel_ms2,
    )

    if (
        limit_state.station_stop_m is not None
        and not _station_stop_continues(limit_state, station_dist_geo, ctx.speed_mph)
    ):
        limit_state.station_stop_m = None

    def _limit_release_ok(pick: Optional[BrakeTargetResult]) -> bool:
        if _station_stop_continues(limit_state, station_dist_geo, ctx.speed_mph):
            return False
        return limit_release_allowed(
            station_dist_geo,
            pick,
            station_target,
            signal_target,
            signal_dist,
            speed_mph=ctx.speed_mph,
        )

    platform_bleed = _attempt_platform_parked_bleed(
        ctx,
        prep,
        station_fsm=station_fsm,
        station_dist_m=station_dist_geo,
        platform_bleed_episode=platform_bleed_episode,
        snap=snap,
    )
    if platform_bleed is not None:
        return platform_bleed

    platform_bleed_release = _attempt_platform_parked_bleed_release(
        ctx,
        prep,
        station_fsm=station_fsm,
        station_dist_m=station_dist_geo,
        platform_bleed_episode=platform_bleed_episode,
        platform_bleed_b1_confirmed=platform_bleed_b1_confirmed,
        snap=snap,
        station_stop_running=limit_state.station_stop_m is not None,
        other_target_active=bool(
            (limit_target is not None and limit_target.apply_now)
            or (signal_target is not None and signal_target.apply_now)
            or (limit_target is not None and limit_target.downhill_hold)
        ),
        limit_sign_passed=prep.dist_m is not None and prep.dist_m <= LIMIT_SIGN_PASSED_M,
    )
    if platform_bleed_release is not None:
        return platform_bleed_release

    departing_release = _attempt_departing_brake_release(
        ctx,
        prep,
        station_fsm=station_fsm,
        station_dist_m=station_dist_geo,
    )
    if departing_release is not None:
        return departing_release

    skip_release = should_skip_p1_release(
        speed_mph=ctx.speed_mph,
        station_dist_m=station_dist_geo,
        combined_lever=prep.combined_lever,
        station_fsm=station_fsm,
        brake_cyl_bar=prep.ctx.cyl,
        platform_bleed_episode=platform_bleed_episode,
    )
    if not skip_release:
        released = _attempt_p1_releases(
            ctx,
            prep,
            limit_state=limit_state,
            release_state=release_state,
            snap=snap,
            target=target,
            station_target=station_target,
            signal_target=signal_target,
            limit_target=limit_target if limit_brake_enabled else None,
            limit_release_ok=_limit_release_ok,
            limit_brake_enabled=limit_brake_enabled,
            signal_brake_enabled=signal_brake_enabled,
        )
        if released is not None:
            return released

    command_target = _overlay_active_zone_hold(target, limit_target)
    if command_target is None:
        if (
            station_dist_geo is None
            and (not limit_brake_enabled or prep.next_limit_mph is None or prep.dist_m is None)
            and signal_target is None
        ):
            return ctx.idle("no_limit_sign")
        continued = _continue_station_stop(
            ctx, limit_state, station_target, station_dist_geo
        )
        if continued is not None:
            return continued
        return ctx.idle("no_plan", target=target)

    decision = _finalize_target_decision(
        ctx,
        command_target,
        limit_state=limit_state,
        release_state=release_state,
        snap=snap,
        learner=learner,
        lever=prep.lever,
        throttle_notch=prep.throttle_notch,
        dist_m=prep.dist_m,
        next_limit_mph=prep.next_limit_mph,
        grad=ctx.grad,
    )
    if target is not None:
        decision.target_kind = target.target_kind
        if target.target_kind == "STATION":
            decision.station_dist_m = target.distance_m
    return decision


def evaluate_limit_tick(
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    snap: ProbeSnapshot,
    *,
    learner: Optional[LearnerProfile] = None,
    predict_decel: Optional[PredictDecelFn] = None,
) -> LimitBrakeDecision:
    """Cartel → ``BrakeCommand`` (delega en ``evaluate_p1_tick``)."""
    return evaluate_p1_tick(
        limit_state,
        release_state,
        snap,
        learner=learner,
        predict_decel=predict_decel,
        station_brake_enabled=False,
        limit_brake_enabled=True,
    )
