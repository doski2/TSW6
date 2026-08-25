#!/usr/bin/env python3
"""
coordinator.py — Orquestación P1 v2 (un módulo por objetivo + prioridad).
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from tsw6.braking.v2.command import (
    BrakeCommand,
    BrakeReleaseState,
    LIMIT_RELEASE_MAX_OVER_MPH,
    governor_action_for_command,
    is_brake_applied,
    is_downhill_limit_approach,
    resolve_release_command,
)
from tsw6.braking.v2.physics import DEFAULT_MAX_BRAKE_DECEL
from tsw6.braking.v2.plan import BrakePlan
from tsw6.braking.v2.cluster import (
    sequential_limit_stop_feasible,
    should_delay_unified_station_plan,
    should_merge_limit_and_station_plans,
)
from tsw6.braking.v2.emergency import check_p1_emergency, is_red_signal_aspect
from tsw6.braking.v2.limit_brake import LimitBrakeState, evaluate_limit_brake
from tsw6.braking.v2.priority import select_urgent_target
from tsw6.braking.v2.signal_brake import evaluate_signal_brake
from tsw6.braking.v2.station_brake import evaluate_station_brake
from tsw6.braking.v2.types import BrakeTargetResult
from tsw6.governor.governor_constants import P1_MIN_NEXT_LIMIT_MPH, STATION_STOPPED_MPH

_log = logging.getLogger("tsw.governor.v2")


class BrakeCoordinatorV2:
    """P1 v2: límite / estación / señal por separado → prioridad Dastsc."""

    def __init__(self) -> None:
        self._limit_state = LimitBrakeState()
        self._release = BrakeReleaseState()
        self.last_target: Optional[BrakeTargetResult] = None
        self.last_brake_command: Optional[BrakeCommand] = None
        self.last_debug: str = ""
        self._unified_stop_latched: bool = False
        self._log_station_dist_m: Optional[float] = None
        self._log_limit_dist_m: Optional[float] = None
        self._log_station_eta: Optional[str] = None

    def reset(self) -> None:
        self._limit_state.reset()
        self._release.reset()
        self.last_target = None
        self.last_brake_command = None
        self.last_debug = ""
        self._unified_stop_latched = False
        self._log_station_dist_m = None
        self._log_limit_dist_m = None
        self._log_station_eta = None

    @property
    def unified_stop_latched(self) -> bool:
        return self._unified_stop_latched

    def investigate_suffix(self) -> str:
        """Campos compactos P1 v2 para la línea de ciclo del autopilot."""
        parts: list[str] = []
        target = self.last_target
        if target is not None:
            parts.append(f"p1tgt={target.target_kind}/{target.phase}")
            parts.append(f"p1d={target.distance_m:.0f}m")
            parts.append(f"p1ds={target.dist_start:.0f}m")
            if target.apply_now:
                parts.append("p1apply=Y")
            if target.detail:
                parts.append(f"p1det={target.detail[:48]}")
        if self._unified_stop_latched:
            parts.append("uni=Y")
        if (
            self._log_station_dist_m is not None
            and self._log_limit_dist_m is not None
        ):
            parts.append(
                f"gap={self._log_station_dist_m - self._log_limit_dist_m:.0f}m"
            )
        if self._log_station_eta:
            parts.append(f"p1eta={self._log_station_eta}")
        cmd = self.last_brake_command
        if cmd is not None:
            if cmd.kind:
                parts.append(f"p1cmd={cmd.kind}")
            if cmd.reason and cmd.reason != self.last_debug:
                parts.append(f"p1r={cmd.reason}")
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
        predict_decel=None,
        speed_limits_ahead: Optional[list] = None,
        station_distance_m: Optional[float] = None,
        station_name: Optional[str] = None,
        brake_transition_s: float = 0.5,
        station_eta: Optional[str] = None,
        station_traveled_m: Optional[float] = None,
        station_anchor_m: Optional[float] = None,
        signal_distance_m: Optional[float] = None,
        signal_aspect: Optional[str] = None,
    ) -> Tuple[Optional[str], float]:
        """
        Returns:
            (action_override, effective_limit) — compatible con SpeedDecider.
        """
        del station_name  # reservado OCR / nombre tablón

        self.last_target = None
        self.last_brake_command = None
        self.last_debug = ""

        grad = gradient_pct or 0.0
        accel = accel_ms2 if accel_ms2 is not None else acceleration_ms2
        base_decel = base_decel_ms2 if base_decel_ms2 > 0 else DEFAULT_MAX_BRAKE_DECEL

        limits_queue = list(speed_limits_ahead or [])
        _nl = next_limit_mph
        _dn = distance_next_m
        if limits_queue:
            _nl = limits_queue[0].get("limit_mph", _nl)
            _dn = limits_queue[0].get("distance_m", _dn)

        self._log_station_dist_m = station_distance_m
        self._log_limit_dist_m = _dn
        self._log_station_eta = station_eta

        self._release.update(speed_mph, _nl)
        _has_station = station_distance_m is not None and station_distance_m > 0

        def _unified_stop_active() -> bool:
            if self._unified_stop_latched:
                return True
            stn_dist = station_distance_m
            if stn_dist is None or stn_dist <= 0 or _dn is None or _nl is None:
                return False
            if not should_merge_limit_and_station_plans(_dn, stn_dist):
                return False
            return not sequential_limit_stop_feasible(
                limit_mph=float(_nl),
                limit_dist_m=float(_dn),
                station_dist_m=stn_dist,
                gradient_pct=grad,
                base_decel=base_decel,
            )

        def _should_block_limit_release() -> bool:
            if not _unified_stop_active():
                return False
            if speed_mph <= STATION_STOPPED_MPH + 1.0:
                return False
            # Cartel cumplido: soltar y coast cartel→andén (no frenar hasta parada).
            if (
                _nl is not None
                and speed_mph <= float(_nl) + LIMIT_RELEASE_MAX_OVER_MPH
            ):
                return False
            return True

        def _attempt_release(plan: Optional[BrakePlan] = None) -> Optional[Tuple[str, float]]:
            if not is_brake_applied(handle_notch):
                return None
            if _should_block_limit_release():
                self.last_debug = "release_blocked:unified_stop"
                return None
            rel = resolve_release_command(
                speed_mph=speed_mph,
                handle_notch=handle_notch,
                effective_limit=effective_limit,
                next_limit_mph=_nl,
                distance_next_m=_dn,
                gradient_pct=grad,
                plan=plan,
            )
            if rel is None:
                return None
            self.last_brake_command = rel
            if (
                _nl is not None
                and not is_downhill_limit_approach(grad, _dn)
                and (plan is None or plan.target_kind == "SPEED_LIMIT")
            ):
                self._release.latch(_nl)
            self.last_debug = "RELEASE→NEU"
            return "RELEASE", effective_limit

        release_result = _attempt_release()
        if release_result is not None:
            return release_result

        if (
            not _has_station
            and (_nl is None or _dn is None or _nl < P1_MIN_NEXT_LIMIT_MPH or _nl >= effective_limit)
        ):
            self.last_debug = "sin_objetivo_v2"
            return None, effective_limit

        unified = _unified_stop_active()
        if unified:
            self._unified_stop_latched = True

        emerg: Optional[Tuple[str, float, BrakeCommand]] = None
        emerg_candidates: list[tuple[float, Tuple[str, float, BrakeCommand]]] = []

        if _has_station and station_distance_m is not None:
            station_emerg = check_p1_emergency(
                target_kind="STATION",
                speed_mph=speed_mph,
                urgent_dist_m=station_distance_m,
                base_decel=base_decel,
                gradient_pct=grad,
                brake_transition_s=brake_transition_s,
                accel_ms2=accel,
            )
            if station_emerg is not None:
                emerg_candidates.append((station_distance_m, station_emerg))

        if (
            signal_distance_m is not None
            and signal_distance_m > 0
            and is_red_signal_aspect(signal_aspect)
        ):
            signal_emerg = check_p1_emergency(
                target_kind="SIGNAL",
                speed_mph=speed_mph,
                urgent_dist_m=signal_distance_m,
                base_decel=base_decel,
                gradient_pct=grad,
                brake_transition_s=brake_transition_s,
                accel_ms2=accel,
            )
            if signal_emerg is not None:
                emerg_candidates.append((signal_distance_m, signal_emerg))

        if emerg_candidates:
            _, emerg = min(emerg_candidates, key=lambda item: item[0])

        if emerg is not None:
            action, eff, cmd = emerg
            self.last_brake_command = cmd
            self.last_debug = cmd.reason
            return action, eff

        candidates: list[BrakeTargetResult] = []

        limit_r = evaluate_limit_brake(
            self._limit_state,
            speed_mph=speed_mph,
            limit_mph=_nl,
            distance_m=_dn,
            gradient_pct=grad,
            accel_ms2=accel,
            base_decel=base_decel,
            predict_decel=predict_decel,
        )
        if limit_r is not None:
            candidates.append(limit_r)

        station_r = evaluate_station_brake(
            speed_mph=speed_mph,
            station_distance_m=station_distance_m,
            gradient_pct=grad,
            base_decel=base_decel,
            predict_decel=predict_decel,
            throttle_notch=throttle_notch,
            station_eta=station_eta,
            station_traveled_m=station_traveled_m,
            station_anchor_m=station_anchor_m,
        )
        if station_r is not None:
            if unified and should_delay_unified_station_plan(
                speed_mph=speed_mph,
                limit_mph=_nl,
                limit_dist_m=_dn,
                station_dist_m=station_distance_m,
            ):
                station_r = None
            if station_r is not None:
                candidates.append(station_r)

        signal_r = evaluate_signal_brake(
            speed_mph=speed_mph,
            signal_distance_m=signal_distance_m,
            signal_aspect=signal_aspect,
            gradient_pct=grad,
            base_decel=base_decel,
            predict_decel=predict_decel,
        )
        if signal_r is not None:
            candidates.append(signal_r)

        if not candidates:
            if speed_mph <= STATION_STOPPED_MPH + 1.0:
                self._unified_stop_latched = False
            self.last_debug = "sin_plan_activo"
            return None, effective_limit

        active = select_urgent_target(
            candidates,
            speed_mph=speed_mph,
            limit_mph=_nl,
            limit_dist_m=_dn,
            station_dist_m=station_distance_m,
            signal_dist_m=signal_distance_m,
            gradient_pct=grad,
        )
        if active is None:
            return None, effective_limit

        release_plan: Optional[BrakePlan] = None
        if active.target_kind == "STATION":
            release_plan = BrakePlan(
                target_kind="STATION",
                distance_to_target_m=active.distance_m,
                target_speed_mph=0.0,
                reaction_margin_m=0.0,
            )
        elif active.target_kind == "SPEED_LIMIT":
            release_plan = BrakePlan(
                target_kind="SPEED_LIMIT",
                distance_to_target_m=active.distance_m,
                target_speed_mph=active.target_speed_mph,
                reaction_margin_m=0.0,
            )

        if is_brake_applied(handle_notch):
            if self._release.should_inhibit_limit_rebrake(
                speed_mph,
                _nl,
                handle_notch,
                release_plan,
                grad,
                _dn,
                effective_limit,
            ):
                blocked = _attempt_release(release_plan)
                if blocked is not None:
                    return blocked
                self.last_debug = "COAST LATCH sin re-freno"
                return "HOLD", effective_limit

            rel_result = _attempt_release(release_plan)
            if rel_result is not None:
                return rel_result

        self.last_target = active
        cmd = active.to_brake_command(
            throttle_notch=throttle_notch,
            current_notch=handle_notch,
            speed_mph=speed_mph,
        )
        if cmd is None:
            self.last_debug = f"{active.target_kind} perfil activo"
            eff = min(effective_limit, active.target_speed_mph or effective_limit)
            if unified and _dn is not None and _nl is not None:
                eff = min(eff, float(_nl))
            return "HOLD", eff

        self.last_brake_command = cmd
        self.last_debug = (
            f"v2 {active.target_kind} {active.phase} "
            f"distStart={active.dist_start:.0f}m notch={cmd.target_notch}"
        )
        if unified:
            self.last_debug += " unified"
        _log.info(
            "P1v2 %s %s dist=%.0fm distStart=%.0fm → %s notch=%s",
            active.target_kind,
            active.phase,
            active.distance_m,
            active.dist_start,
            cmd.display_action(),
            cmd.target_notch,
        )

        action = governor_action_for_command(cmd)
        eff = min(effective_limit, active.target_speed_mph or effective_limit)
        if unified and _dn is not None and _nl is not None:
            eff = min(eff, float(_nl))
        if speed_mph <= STATION_STOPPED_MPH + 1.0:
            self._unified_stop_latched = False
        return action, eff
