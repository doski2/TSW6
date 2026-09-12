"""Conversión plan v→0 → ``BrakeTargetResult`` (andén / señal)."""

from __future__ import annotations

from typing import Optional

from tsw6v2.physics import should_emit_brake_command
from tsw6v2.plan import BrakePlan
from tsw6v2.target import BrakeTargetResult


def target_from_stop_plan(
    plan: BrakePlan,
    *,
    speed_mph: float,
    detail: str,
    allow_watch: bool = False,
) -> Optional[BrakeTargetResult]:
    """Activo APPLY; opcional WATCH si ``allow_watch`` y aún lejos de ventana."""
    step = plan.active_step
    if step is None:
        return None
    emit = should_emit_brake_command(
        apply_now=step.apply_now,
        dist_start=step.dist_start,
        speed_mph=speed_mph,
        distance_to_target_m=plan.distance_to_target_m,
        apply_at_remaining_m=step.apply_at_remaining_m,
    )
    if not emit:
        late = [s for s in plan.steps if s.dist_start <= 0]
        if late:
            step = late[-1]
            emit = should_emit_brake_command(
                apply_now=True,
                dist_start=step.dist_start,
                speed_mph=speed_mph,
                distance_to_target_m=plan.distance_to_target_m,
                apply_at_remaining_m=step.apply_at_remaining_m,
            )
    if not emit:
        if not allow_watch:
            return None
        watch = next((s for s in plan.steps if s.dist_start > 0), step)
        if watch is None:
            return None
        return BrakeTargetResult(
            target_kind=plan.target_kind,
            distance_m=plan.distance_to_target_m,
            target_speed_mph=plan.target_speed_mph,
            handle_notch=watch.handle_notch,
            phase=watch.notch,
            dist_start=watch.dist_start,
            apply_now=False,
            detail=detail,
        )
    return BrakeTargetResult(
        target_kind=plan.target_kind,
        distance_m=plan.distance_to_target_m,
        target_speed_mph=plan.target_speed_mph,
        handle_notch=step.handle_notch,
        phase=step.notch,
        dist_start=step.dist_start,
        apply_now=True,
        detail=detail,
    )
