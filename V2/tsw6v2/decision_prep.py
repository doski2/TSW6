"""Preparación del tick P1: contexto, datos del vehículo y tipo de freno (telemetría)."""

from __future__ import annotations

from typing import Callable, Optional

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import (
    combined_lever_for_station_gate,
    throttle_notch_from_probe,
)
from tsw6v2.constants import MS_TO_MPH, NEUTRAL_NOTCH
from tsw6v2.decision_types import TickCtx, TickPrep
from tsw6v2.ipc import probe_lever
from tsw6v2.learner import LearnerProfile, _predict_for_kind
from tsw6v2.physics import DEFAULT_BRAKE_FILL_S, set_active_physics
from tsw6v2.plan import PredictDecelFn
from tsw6v2.planning import effective_limit_mph, next_speed_limit
from tsw6v2.vehicle_package import (
    mc_first_click_fraction,
    vehicle_package_from_snap,
    vehicle_physics,
)


def escalate_cap_fn(
    learner: LearnerProfile,
    cyl: Optional[float],
) -> Callable[[int, int], int]:
    def _cap(prev: int, stepped: int) -> int:
        return learner.cap_escalation(
            committed=prev,
            requested=stepped,
            brake_cyl_bar=cyl,
        )

    return _cap


BRAKE_KIND_EPS = 0.02


def brake_applied(train_brake: Optional[float], dyn_brake: Optional[float]) -> bool:
    """Freno realmente aplicado (aire o dinámico) según telemetría."""
    return (
        float(train_brake or 0.0) > BRAKE_KIND_EPS
        or float(dyn_brake or 0.0) > BRAKE_KIND_EPS
    )


def brake_kind(train_brake: Optional[float], dyn_brake: Optional[float]) -> str:
    """``air`` | ``dyn`` | ``mixed`` según aire (train_brake) y dinámico (dyn_brake)."""
    tb = float(train_brake or 0.0)
    db = float(dyn_brake or 0.0)
    if tb > BRAKE_KIND_EPS and db > BRAKE_KIND_EPS:
        return "mixed"
    if db > BRAKE_KIND_EPS:
        return "dyn"
    return "air"


def prepare_tick(
    snap: ProbeSnapshot,
    learner: Optional[LearnerProfile],
    predict_decel: Optional[PredictDecelFn],
) -> Optional[TickPrep]:
    if snap.speed_ms is None:
        return None
    dist_m, next_limit_mph = next_speed_limit(snap)
    lever = probe_lever(snap)
    if lever is None:
        lever = NEUTRAL_NOTCH
    vehicle_pkg = vehicle_package_from_snap(snap)
    physics = vehicle_physics(vehicle_pkg)
    set_active_physics(physics)
    combined_lever = combined_lever_for_station_gate(snap, lever, vehicle_pkg)
    ctx = TickCtx(
        dist_m=dist_m,
        next_limit_mph=next_limit_mph,
        effective=effective_limit_mph(snap),
        speed_mph=float(snap.speed_ms) * MS_TO_MPH,
        grad=float(snap.gradient_pct or 0.0),
        lever=lever,
        cyl=snap.brake_cyl_bar,
        vehicle_package=vehicle_pkg,
        physics=physics,
        click_decel_ms2=(
            learner.mc_decel_for(mc_first_click_fraction(vehicle_pkg))
            if learner is not None and vehicle_pkg is not None
            else None
        ),
        mc_decel_table=(
            learner.mc_decel_table()
            if learner is not None and vehicle_pkg is not None
            else None
        ),
    )
    if learner is not None:
        learner.observe_air(lever, ctx.cyl)
    return TickPrep(
        ctx=ctx,
        dist_m=dist_m,
        next_limit_mph=next_limit_mph,
        lever=lever,
        combined_lever=combined_lever,
        throttle_notch=throttle_notch_from_probe(snap, vehicle_pkg),
        escalate_cap=escalate_cap_fn(learner, ctx.cyl) if learner else None,
        fill_s=learner.brake_fill_s if learner else DEFAULT_BRAKE_FILL_S,
        predict=predict_decel or (
            _predict_for_kind(learner, brake_kind(snap.train_brake, snap.dyn_brake))
            if learner
            else None
        ),
    )
