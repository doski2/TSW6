#!/usr/bin/env python3
"""
braking_advisor.py — Frenado anticipatorio (P1) con planificador Dastsc.

Seguridad inmediata (P1-CRITICO / P1-EMERGENCIA) + plan por pasos B1–B3
(``brake_planner.py``, puerto de Dastsc planBrake.ts).
"""

import logging
from typing import Optional, Tuple

from tsw6.braking.brake_command import (
    BrakeCommand,
    governor_action_for_command,
    plan_to_brake_command,
)
from tsw6.braking.brake_planner import BrakePlan, plan_for_speed_limits
from tsw6.braking.brake_release import (
    BrakeReleaseState,
    is_brake_applied,
    is_downhill_limit_approach,
    resolve_release_command,
)
from tsw6.governor.governor_constants import (
    P1_MIN_NEXT_LIMIT_MPH, P1_REACT_S, P1_ACK_GUARD_S,
    P1_EMERGENCIA_DIST, P1_EMERGENCIA_MPH,
    P1_CRITICO_DIST, P1_CRITICO_MPH,
)

_log = logging.getLogger("tsw.governor")


class BrakingAdvisor:
    """Frenado anticipatorio: plan Dastsc + overrides de emergencia."""

    def __init__(self) -> None:
        self._last_next_limit: Optional[float] = None
        self.last_plan: Optional[BrakePlan] = None
        self.last_brake_command: Optional[BrakeCommand] = None
        self._release = BrakeReleaseState()

    def reset(self) -> None:
        self._last_next_limit = None
        self.last_plan = None
        self.last_brake_command = None
        self._release.reset()

    def evaluate(
        self,
        speed_mph: float,
        next_limit_mph: Optional[float],
        distance_next_m: Optional[float],
        effective_limit: float,
        gradient_pct: Optional[float],
        acceleration_ms2: Optional[float],
        braking_distance_fn,
        should_brake_fn,
        eff_k_stop: float,
        throttle_notch: int,
        speed_limits_ahead: Optional[list] = None,
        base_decel_ms2: float = 0.0,
        predict_decel=None,
        handle_notch: int = 4,
    ) -> Tuple[Optional[str], float]:
        """
        Evalúa frenado anticipatorio.

        Returns:
            (action_override, effective_limit)
        """
        self.last_plan = None
        self.last_brake_command = None

        grad = gradient_pct or 0.0
        limits_queue = list(speed_limits_ahead or [])

        # Objetivo principal: cola unificada o par next_limit/dist
        if not limits_queue and next_limit_mph is not None and distance_next_m is not None:
            limits_queue = [{
                "limit_mph": next_limit_mph,
                "distance_m": distance_next_m,
            }]

        _nl = next_limit_mph
        _dn = distance_next_m
        if limits_queue:
            _nl = limits_queue[0].get("limit_mph", _nl)
            _dn = limits_queue[0].get("distance_m", _dn)

        if _nl is not None and self._last_next_limit is not None:
            if abs(_nl - self._last_next_limit) > 2.0:
                pass
        self._last_next_limit = _nl

        self._release.update(speed_mph, _nl)

        if is_brake_applied(handle_notch):
            release_cmd = resolve_release_command(
                speed_mph=speed_mph,
                handle_notch=handle_notch,
                effective_limit=effective_limit,
                next_limit_mph=_nl,
                distance_next_m=_dn,
                gradient_pct=grad,
            )
            if release_cmd is not None:
                self.last_brake_command = release_cmd
                if _nl is not None and not is_downhill_limit_approach(grad, _dn):
                    self._release.latch(_nl)
                return "RELEASE", effective_limit

        if (_nl is None or _dn is None
                or _nl < P1_MIN_NEXT_LIMIT_MPH
                or _nl >= effective_limit):
            return None, effective_limit

        _accel = acceleration_ms2
        bd = braking_distance_fn(
            speed_mph, _nl,
            gradient_pct=grad,
            current_accel_ms2=_accel,
        )
        _exceso = speed_mph - _nl

        # ── P1-CRITICO ──────────────────────────────────────────────────────
        if _dn <= P1_CRITICO_DIST and _exceso > P1_CRITICO_MPH:
            _log.critical(
                "P1 CRITICO  spd=%.1f  next_lim=%.1f  dist=%.0fm  exceso=%.1f",
                speed_mph, _nl, _dn, _exceso)
            self.last_brake_command = BrakeCommand(
                kind="APPLY", target_notch=0, phase="B3", reason="P1-CRITICO")
            return "FULLSTOP", _nl

        # ── P1-EMERGENCIA ───────────────────────────────────────────────────
        if ((_exceso > 0 and _dn <= bd * 0.5)
                or (_dn <= P1_EMERGENCIA_DIST and _exceso > P1_EMERGENCIA_MPH)):
            _log.warning(
                "P1 EMERGENCIA  spd=%.1f  next_lim=%.1f  dist=%.0fm  bd=%.0fm  exceso=%.1f",
                speed_mph, _nl, _dn, bd, _exceso)
            self.last_brake_command = BrakeCommand(
                kind="APPLY", target_notch=0, phase="B3", reason="P1-EMERGENCIA")
            return "HOLD", _nl

        # ── Plan Dastsc (servicio + perfil gradual) ───────────────────────
        decel = base_decel_ms2 if base_decel_ms2 > 0 else 0.80
        plan = plan_for_speed_limits(
            speed_mph, limits_queue, effective_limit, grad, decel,
            predict_decel=predict_decel)
        if plan is not None:
            self.last_plan = plan
            if self._release.should_inhibit_limit_rebrake(
                speed_mph,
                _nl,
                handle_notch,
                plan,
                grad,
                _dn,
                effective_limit,
            ):
                _log.debug(
                    "P1 COAST LATCH  spd=%.1f  next_lim=%.1f  — sin re-freno",
                    speed_mph, _nl)
                eff = plan_to_brake_command(
                    plan,
                    speed_mph=speed_mph,
                    throttle_notch=0,
                    effective_limit=effective_limit,
                    current_notch=handle_notch,
                )[1]
                return "HOLD", eff

            cmd, eff = plan_to_brake_command(
                plan,
                speed_mph=speed_mph,
                throttle_notch=throttle_notch,
                effective_limit=effective_limit,
                current_notch=handle_notch,
            )
            if cmd is not None:
                self.last_brake_command = cmd
                step = plan.active_step
                p1_action = governor_action_for_command(cmd)
                _log.info(
                    "P1 PLAN %s  %s dist=%.0fm  distStart=%.0fm  apply=%s  "
                    "learned=%s  → %s notch=%s",
                    plan.target_kind,
                    step.notch if step else "?",
                    plan.distance_to_target_m,
                    step.dist_start if step else 0,
                    step.apply_now if step else False,
                    step.using_learned if step else False,
                    cmd.display_action(),
                    cmd.target_notch,
                )
                return p1_action, eff

            eff = plan_to_brake_command(
                plan,
                speed_mph=speed_mph,
                throttle_notch=0,
                effective_limit=effective_limit,
                current_notch=handle_notch,
            )[1]
            if eff < effective_limit - 0.1:
                _log.debug(
                    "P1 PERFIL  spd=%.1f  next_lim=%.1f  elim→%.1f",
                    speed_mph, _nl, eff)
                if throttle_notch > 0 and should_brake_fn(
                        speed_mph, _nl, _dn,
                        gradient_pct=grad,
                        react_s=(P1_REACT_S + P1_ACK_GUARD_S),
                        current_accel_ms2=_accel):
                    self.last_brake_command = BrakeCommand(
                        kind="COAST_THROTTLE",
                        target_notch=4,
                        reason="P1 perfil — soltar tracción",
                    )
                    return "COAST", eff
                return "HOLD", eff

        return None, effective_limit
