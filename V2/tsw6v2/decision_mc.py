"""Lógica MC (palanca analógica) del tick P1: parada en andén y cartel con eje continuo."""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from tsw6v2.command import BrakeCommand
from tsw6v2.constants import NEUTRAL_NOTCH
from tsw6v2.decision_types import LimitBrakeDecision, TickCtx, decide_station_neutral_release
from tsw6v2.limits import LimitBrakeState
from tsw6v2.target import BrakeTargetResult
from tsw6v2.vehicle_adapter import adapter_for_package


def station_stop_continues(
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
    frac = adapter_for_package(ctx.vehicle_package).station_stop_fraction(
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
    """¿Rodar en neutro hasta el clic? Misma regla para el plan y para ``continue_station_stop``."""
    return adapter_for_package(ctx.vehicle_package).roll_until_click(
        speed_mph=ctx.speed_mph,
        distance_m=distance_m,
        gradient_pct=ctx.grad,
        click_decel_ms2=ctx.click_decel_ms2,
        running=running,
        latch=limit_state.roll_latch_for(running),
    )


def continue_station_stop(
    ctx: TickCtx,
    limit_state: LimitBrakeState,
    target: Optional[BrakeTargetResult],
    station_dist_m: Optional[float] = None,
) -> Optional[LimitBrakeDecision]:
    dist = station_dist_m
    if dist is None and target is not None and target.target_kind == "STATION":
        dist = target.distance_m
    if dist is None or not station_stop_continues(limit_state, dist, ctx.speed_mph):
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
        return decide_station_neutral_release(ctx, rel, "station_roll")
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


def mc_station_stop_fraction(
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
    running = station_stop_continues(limit_state, target.distance_m, ctx.speed_mph)
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


def mc_limit_fraction(
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
    frac = adapter_for_package(ctx.vehicle_package).limit_fraction(
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
