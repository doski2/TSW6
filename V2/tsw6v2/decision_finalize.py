"""Cierre del tick P1: del objetivo ganador a ``LimitBrakeDecision`` (bloqueo de aire, fracción MC)."""

from __future__ import annotations

from typing import Optional

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeCommand, BrakeReleaseState
from tsw6v2.constants import NOTCH_WEAKEN_HOLD_SEQ
from tsw6v2.decision_mc import (
    continue_station_stop,
    mc_limit_fraction,
    mc_station_stop_fraction,
)
from tsw6v2.decision_types import LimitBrakeDecision, TickCtx, TickPrep
from tsw6v2.learner import LearnerProfile
from tsw6v2.limits import LimitBrakeState
from tsw6v2.target import BrakeTargetResult
from tsw6v2.vehicle_adapter import adapter_for_package


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


def _notch_weaken_blocked(
    limit_state: LimitBrakeState,
    cmd: BrakeCommand,
    lever: int,
    seq: Optional[int],
    *,
    notch_layout: bool,
) -> bool:
    """¿Aflojar la muesca (B2→B1) demasiado pronto tras el último cambio del plan?

    Solo layout por muescas y con ``seq``. Handle mayor = freno más débil (1 = B3, 3 = B1).
    """
    if not notch_layout or seq is None or cmd.kind != "APPLY" or cmd.target_notch is None:
        return False
    last = limit_state.notch_change_seq
    if last is None:
        return False
    target, current = int(cmd.target_notch), int(lever)
    if not 1 <= current <= 3 or target <= current:
        return False
    return 0 <= seq - last < NOTCH_WEAKEN_HOLD_SEQ


def _plan_reason(cmd: BrakeCommand, target: BrakeTargetResult) -> str:
    if cmd.kind == "RELEASE":
        return "release"
    if cmd.kind == "COAST_THROTTLE":
        return "coast_throttle"
    if target.downhill_hold and cmd.kind == "APPLY":
        return "downhill_hold"
    return "plan"




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
    cmd = mc_station_stop_fraction(cmd, target, ctx, limit_state)
    cmd = mc_limit_fraction(cmd, target, ctx, limit_state)

    if cmd is None or (cmd.kind == "APPLY" and not target.apply_now):
        continued = continue_station_stop(ctx, limit_state, target)
        if continued is not None:
            return continued
        if cmd is None:
            return ctx.idle("command_none", target=target)
        return ctx.idle("apply_deferred", target=target)

    notch_layout = not adapter_for_package(ctx.vehicle_package).analog_lever
    seq = getattr(snap, "seq", None)
    if _notch_weaken_blocked(limit_state, cmd, lever, seq, notch_layout=notch_layout):
        return ctx.idle("notch_dwell", target=target, detail="Esperar antes de aflojar la muesca")

    air_block = _air_apply_block(learner, cmd, ctx.cyl, lever)
    if air_block is not None:
        reason, detail = air_block
        return ctx.idle(reason, target=target, detail=detail)

    decision = ctx.from_target(cmd, target, _plan_reason(cmd, target))
    if (
        notch_layout
        and seq is not None
        and cmd.kind == "APPLY"
        and cmd.target_notch is not None
        and int(cmd.target_notch) != int(lever)
    ):
        limit_state.notch_change_seq = int(seq)
    if (
        target.target_kind == "STATION"
        and cmd.kind == "APPLY"
        and not adapter_for_package(ctx.vehicle_package).analog_lever
    ):
        # Layout por muescas (323): el freno de la parada en curso es del plan de estación.
        # Sin esto el tick siguiente (palanca ya en freno) caía en «objetivo alcanzado» del
        # cartel y soltaba: APPLY/RELEASE cada tick (20261023T211407Z, 485-510 s, 26 pares).
        # El layout analógico ya lo fija en ``mc_station_stop_fraction``.
        limit_state.station_stop_m = target.distance_m
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


def finalize_p1_decision(
    ctx: TickCtx,
    prep: TickPrep,
    snap: ProbeSnapshot,
    *,
    target: Optional[BrakeTargetResult],
    limit_target: Optional[BrakeTargetResult],
    station_target: Optional[BrakeTargetResult],
    signal_target: Optional[BrakeTargetResult],
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    learner: Optional[LearnerProfile],
    limit_brake_enabled: bool,
    station_dist_geo: Optional[float],
) -> LimitBrakeDecision:
    """Último tramo del tick: mando del objetivo ganador (o ``no_plan`` / ``no_limit_sign``)."""
    command_target = _overlay_active_zone_hold(target, limit_target)
    if command_target is None:
        if (
            station_dist_geo is None
            and (not limit_brake_enabled or prep.next_limit_mph is None or prep.dist_m is None)
            and signal_target is None
        ):
            return ctx.idle("no_limit_sign")
        continued = continue_station_stop(
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
