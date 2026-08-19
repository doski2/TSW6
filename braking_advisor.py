#!/usr/bin/env python3
"""
braking_advisor.py — Frenado anticipatorio (P1) con planificador Dastsc.

Seguridad inmediata (P1-CRITICO / P1-EMERGENCIA) + plan por pasos B1–B3
(``brake_planner.py``, puerto de Dastsc planBrake.ts).
"""

import logging
from typing import Optional, Tuple

from brake_planner import plan_for_speed_limits, plan_to_governor_action
from governor_constants import (
    P1_MIN_NEXT_LIMIT_MPH, P1_REACT_S, P1_ACK_GUARD_S,
    P1_EMERGENCIA_DIST, P1_EMERGENCIA_MPH,
    P1_CRITICO_DIST, P1_CRITICO_MPH,
)

_log = logging.getLogger("tsw.governor")


class BrakingAdvisor:
    """Frenado anticipatorio: plan Dastsc + overrides de emergencia."""

    def __init__(self) -> None:
        self._last_next_limit: Optional[float] = None

    def reset(self) -> None:
        self._last_next_limit = None

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
    ) -> Tuple[Optional[str], float]:
        """
        Evalúa frenado anticipatorio.

        Returns:
            (action_override, effective_limit)
        """
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
            return "FULLSTOP", _nl

        # ── P1-EMERGENCIA ───────────────────────────────────────────────────
        if ((_exceso > 0 and _dn <= bd * 0.5)
                or (_dn <= P1_EMERGENCIA_DIST and _exceso > P1_EMERGENCIA_MPH)):
            _log.warning(
                "P1 EMERGENCIA  spd=%.1f  next_lim=%.1f  dist=%.0fm  bd=%.0fm  exceso=%.1f",
                speed_mph, _nl, _dn, bd, _exceso)
            return "HARDBRAKE", _nl

        # ── Plan Dastsc (servicio + perfil gradual) ───────────────────────
        decel = base_decel_ms2 if base_decel_ms2 > 0 else 0.80
        plan = plan_for_speed_limits(
            speed_mph, limits_queue, effective_limit, grad, decel,
            predict_decel=predict_decel)
        if plan is not None:
            action, eff = plan_to_governor_action(
                plan,
                speed_mph=speed_mph,
                throttle_notch=throttle_notch,
                effective_limit=effective_limit,
            )
            if action is not None:
                step = plan.active_step
                _log.info(
                    "P1 PLAN %s  %s dist=%.0fm  distStart=%.0fm  apply=%s  "
                    "learned=%s  → %s",
                    plan.target_kind,
                    step.notch if step else "?",
                    plan.distance_to_target_m,
                    step.dist_start if step else 0,
                    step.apply_now if step else False,
                    step.using_learned if step else False,
                    action,
                )
                return action, eff

            eff = plan_to_governor_action(
                plan,
                speed_mph=speed_mph,
                throttle_notch=0,
                effective_limit=effective_limit,
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
                    return "COAST", eff
                return None, eff

        # Fallback: física legacy should_brake
        if should_brake_fn(
                speed_mph, _nl, _dn,
                gradient_pct=grad,
                react_s=(P1_REACT_S + P1_ACK_GUARD_S),
                current_accel_ms2=_accel):
            eff = min(effective_limit, _nl + max(0.0, _exceso) * 0.3)
            if throttle_notch > 0:
                return "COAST", eff
            return "BRAKE", eff

        return None, effective_limit
