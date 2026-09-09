"""P1 cartel para autopilot v1 — delega en ``evaluate_limit_tick`` (sin coordinator v1)."""

from __future__ import annotations

import logging
from typing import Callable, Optional, Tuple

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.constants import MPH_TO_MS
from tsw6v2.decision import evaluate_p1_tick
from tsw6v2.limits import LimitBrakeState
from tsw6v2.planning import resolve_limit_objective
from tsw6v2.station_plan import STATION_SCHEDULE_SLACK_ENABLED
from tsw6v2.target import BrakeTargetKind, BrakeTargetResult
from tsw6v2.command import (
    BrakeCommand,
    BrakeReleaseState,
    governor_action_for_command,
)

_log = logging.getLogger("tsw6v2.autopilot_limit")

PredictDecelFn = Callable[[int, float, float], Optional[float]]


def snapshot_from_autopilot(
    *,
    speed_mph: float,
    effective_limit: float,
    next_limit_mph: Optional[float],
    distance_next_m: Optional[float],
    gradient_pct: float,
    handle_notch: int,
    accel_ms2: Optional[float],
) -> ProbeSnapshot:
    return ProbeSnapshot(
        speed_ms=float(speed_mph) * MPH_TO_MS,
        speed_limit_ms=float(effective_limit) * MPH_TO_MS,
        next_limit_ms=(
            float(next_limit_mph) * MPH_TO_MS if next_limit_mph is not None else None
        ),
        dist_limit_cm=(
            float(distance_next_m) * 100.0 if distance_next_m is not None else None
        ),
        gradient_pct=float(gradient_pct),
        accel_ms2=accel_ms2,
        handle_notch=int(handle_notch),
    )


class LimitP1Adapter:
    """Sustituto limit-only de ``BrakeCoordinatorV2`` para ``SpeedDecider``."""

    def __init__(self) -> None:
        self._limit_state = LimitBrakeState()
        self._release = BrakeReleaseState()
        self.last_target: Optional[BrakeTargetResult] = None
        self.last_brake_command: Optional[BrakeCommand] = None
        self.last_debug: str = ""

    def reset(self) -> None:
        self._limit_state.reset()
        self._release.reset()
        self.last_target = None
        self.last_brake_command = None
        self.last_debug = ""

    @property
    def unified_stop_latched(self) -> bool:
        return False

    def set_schedule_slack_enabled(self, enabled: bool) -> None:
        del enabled

    def investigate_suffix(self) -> str:
        parts: list[str] = []
        target = self.last_target
        if target is not None:
            parts.append(f"p1tgt={target.target_kind}/{target.phase}")
            parts.append(f"p1d={target.distance_m:.0f}m")
            parts.append(f"p1ds={target.dist_start:.0f}m")
            if target.apply_now:
                parts.append("p1apply=Y")
        cmd = self.last_brake_command
        if cmd is not None:
            parts.append(f"p1cmd={cmd.kind}")
            if cmd.reason:
                parts.append(f"p1r={cmd.reason[:48]}")
        return "  ".join(parts)

    def evaluate(
        self,
        *,
        speed_mph: float,
        next_limit_mph: Optional[float],
        distance_next_m: Optional[float],
        effective_limit: float,
        gradient_pct: float,
        accel_ms2: Optional[float] = None,
        acceleration_ms2: Optional[float] = None,
        throttle_notch: int,
        handle_notch: int,
        base_decel_ms2: float,
        predict_decel: Optional[PredictDecelFn] = None,
        **kwargs,
    ) -> Tuple[Optional[str], float]:
        del throttle_notch, base_decel_ms2
        self.last_target = None
        self.last_brake_command = None
        self.last_debug = ""

        accel = accel_ms2 if accel_ms2 is not None else acceleration_ms2
        speed_limits_ahead = kwargs.get("speed_limits_ahead")
        nl, dn = resolve_limit_objective(
            speed_mph=speed_mph,
            effective_limit=effective_limit,
            next_limit_mph=next_limit_mph,
            distance_next_m=distance_next_m,
            speed_limits_ahead=speed_limits_ahead,
        )
        snap = snapshot_from_autopilot(
            speed_mph=speed_mph,
            effective_limit=effective_limit,
            next_limit_mph=nl,
            distance_next_m=dn,
            gradient_pct=gradient_pct,
            handle_notch=handle_notch,
            accel_ms2=accel,
        )
        station_dist = kwargs.get("station_distance_m")
        station_eta = kwargs.get("station_eta")
        station_m = (
            float(station_dist)
            if station_dist is not None and float(station_dist) > 0
            else None
        )
        decision = evaluate_p1_tick(
            self._limit_state,
            self._release,
            snap,
            predict_decel=predict_decel,
            station_distance_m=station_m,
            station_eta=station_eta,
            schedule_slack_enabled=kwargs.get(
                "schedule_slack_enabled", STATION_SCHEDULE_SLACK_ENABLED
            ),
        )
        eff = effective_limit
        kind: BrakeTargetKind = (
            "STATION"
            if decision.target_kind == "STATION"
            else "SIGNAL"
            if decision.target_kind == "SIGNAL"
            else "SPEED_LIMIT"
        )
        dist_m = decision.station_dist_m
        if dist_m is None and decision.limit_dist_m is not None:
            dist_m = float(decision.limit_dist_m)
        tgt_speed = 0.0 if kind == "STATION" else float(decision.limit_mph or 0.0)
        if dist_m is not None and (decision.limit_mph is not None or kind == "STATION"):
            self.last_target = BrakeTargetResult(
                target_kind=kind,
                distance_m=float(dist_m),
                target_speed_mph=tgt_speed,
                handle_notch=int(decision.handle_notch or 3),
                phase=decision.phase or "B1",
                dist_start=float(decision.dist_start_m or 0.0),
                apply_now=bool(decision.apply_now),
                detail=decision.detail,
            )

        cmd = decision.command
        if cmd is None:
            self.last_debug = decision.reason or decision.detail or "sin_plan_activo"
            return None, eff

        self.last_brake_command = cmd
        tgt_label = kind
        dist_log = (
            decision.station_dist_m
            if kind == "STATION"
            else decision.limit_dist_m
        ) or 0.0
        self.last_debug = (
            f"v2 {tgt_label} {decision.phase or cmd.phase or ''} "
            f"distStart={decision.dist_start_m or 0:.0f}m notch={cmd.target_notch}"
        ).strip()
        if cmd.kind == "APPLY":
            _log.info(
                "P1v2 %s %s dist=%.0fm distStart=%.0fm → %s notch=%s",
                tgt_label,
                decision.phase or cmd.phase,
                dist_log,
                decision.dist_start_m or 0.0,
                cmd.display_action(),
                cmd.target_notch,
            )
        return governor_action_for_command(cmd), eff


# Alias histórico (tests / imports v1)
BrakeCoordinatorV2 = LimitP1Adapter
