#!/usr/bin/env python3
"""
braking_advisor.py — Lógica de frenado anticipatorio (P1).

Extraída de speed_governor.py para reducir su complejidad.
Implementa 4 niveles de urgencia progresiva:
  P1-CRITICO:    dist ≤ 20m con exceso > 10mph → FULLSTOP
  P1-EMERGENCIA: dist ≤ bd×0.5 O dist ≤ 50m con exceso > 5mph → HARDBRAKE
  P1-SERVICIO:   dist ≤ bd → BRAKE
  P1-ALERTA:     dist ≤ bd_hor × 1.5 → perfil gradual (reduce effective_limit)
"""

import logging
import math
from typing import Optional, Tuple

from governor_constants import (
    P1_MIN_NEXT_LIMIT_MPH, P1_REACT_S, P1_ACK_GUARD_S,
    P1_ALERTA_FACTOR, P1_EMERGENCIA_DIST, P1_EMERGENCIA_MPH,
    P1_CRITICO_DIST, P1_CRITICO_MPH,
)

_log = logging.getLogger("tsw.governor")


class BrakingAdvisor:
    """
    Calcula frenado anticipatorio (P1) ante el próximo límite de velocidad.
    Devuelve una acción override y/o un effective_limit ajustado.
    """

    def __init__(self):
        self._nomarker_cycles: int = 0
        self._last_next_limit: Optional[float] = None

    def reset(self) -> None:
        """Reset state when P1 not active."""
        self._nomarker_cycles = 0
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
    ) -> Tuple[Optional[str], float]:
        """
        Evalúa si necesita frenar anticipadamente.

        Returns:
            (action_override, effective_limit):
                action_override: 'FULLSTOP'|'HARDBRAKE'|'BRAKE'|'COAST'|None
                effective_limit: posiblemente reducido por perfil P1-ALERTA
        """
        _nl = next_limit_mph
        _dn = distance_next_m

        # ── Frenado anticipatorio desde planning_delta speed_limits ────────────
        if speed_limits_ahead:
            for sl in speed_limits_ahead:
                sl_limit = sl.get("limit_mph")
                sl_dist = sl.get("distance_m")
                if sl_limit is None or sl_dist is None:
                    continue
                if sl_limit >= speed_mph:
                    continue
                bd_needed = braking_distance_fn(
                    speed_mph, sl_limit, gradient_pct=gradient_pct) * 1.2
                if sl_dist <= bd_needed:
                    if _nl is None or sl_limit < _nl or (_dn is not None and sl_dist < _dn):
                        _nl = sl_limit
                        _dn = sl_dist

        # Reset ciclos si next_limit cambia más de 2 mph
        if _nl is not None and self._last_next_limit is not None:
            if abs(_nl - self._last_next_limit) > 2.0:
                self._nomarker_cycles = 0
        self._last_next_limit = _nl

        # Filtro: usar siempre que next_limit < effective_limit
        if (_nl is None or _dn is None
                or _nl < P1_MIN_NEXT_LIMIT_MPH
                or _nl >= effective_limit):
            self._nomarker_cycles = 0
            return None, effective_limit

        v_ms = speed_mph * 0.44704
        _grad_factor = 1.0 + abs(gradient_pct or 0.0) / 2.0
        react_m = v_ms * (P1_REACT_S + P1_ACK_GUARD_S) * _grad_factor
        _accel = acceleration_ms2
        bd = braking_distance_fn(speed_mph, _nl,
                                 gradient_pct=gradient_pct,
                                 current_accel_ms2=_accel)
        bd_hor = max(bd + react_m, 1.0)
        profile_cap = effective_limit
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
            self._nomarker_cycles += 1
            _log.warning(
                "P1 EMERGENCIA  spd=%.1f  next_lim=%.1f  dist=%.0fm  bd=%.0fm  exceso=%.1f",
                speed_mph, _nl, _dn, bd, _exceso)
            return "HARDBRAKE", _nl

        # ── P1-SERVICIO ─────────────────────────────────────────────────────
        if _exceso > 0 and _dn <= bd:
            self._nomarker_cycles += 1
            if self._nomarker_cycles == 1:
                _log.warning(
                    "P1 SERVICIO (COAST)  spd=%.1f  next_lim=%.1f  dist=%.0fm  bd=%.0fm",
                    speed_mph, _nl, _dn, bd)
                eff = min(effective_limit, _nl + _exceso * 0.3)
                if throttle_notch > 0:
                    return "COAST", eff
                return "BRAKE", eff
            _log.warning(
                "P1 SERVICIO (BRAKE)  spd=%.1f  next_lim=%.1f  dist=%.0fm  bd=%.0fm",
                speed_mph, _nl, _dn, bd)
            return "BRAKE", min(effective_limit, _nl)

        # ── P1-ALERTA: perfil gradual ───────────────────────────────────────
        if _nl < speed_mph - 0.3:
            _frac = min(1.0, _dn / bd_hor)
            profile_cap = _nl + (speed_mph - _nl) * _frac
            k2 = eff_k_stop ** 2
            p1_ceil = math.sqrt(_nl ** 2 + k2 * (_dn + react_m))
            profile_cap = min(profile_cap, p1_ceil)
            effective_limit = min(effective_limit, profile_cap)
            _log.debug(
                "P1 ALERTA perfil  spd=%.1f  next_lim=%.1f  dist=%.0fm  "
                "bd_hor=%.0fm  cap=%.1f",
                speed_mph, _nl, _dn, bd_hor, profile_cap)

            # B/D: Pre-frenado con gradiente favorable (bajada hacia límite inferior)
            # Si estamos en bajada y la gravedad ayuda a acelerar, iniciar COAST antes
            if (gradient_pct is not None and gradient_pct < -0.5
                    and _dn <= bd_hor * 1.2
                    and throttle_notch > 0):
                return "COAST", effective_limit

        if should_brake_fn(speed_mph, _nl, _dn,
                           gradient_pct=gradient_pct,
                           react_s=(P1_REACT_S + P1_ACK_GUARD_S) * _grad_factor,
                           current_accel_ms2=_accel):
            # La física dice que ya hay que frenar: reducir el límite Y devolver COAST
            # para garantizar que el gobernador actúe sin esperar a que P2 lo detecte.
            effective_limit = min(effective_limit, profile_cap)
            _log.debug(
                "P1 ALERTA (should_brake)  spd=%.1f  next_lim=%.1f  dist=%.0fm  cap=%.1f  → COAST",
                speed_mph, _nl, _dn, profile_cap)
            if throttle_notch > 0:
                return "COAST", effective_limit

        # No urgency triggered → reset cycles
        self._nomarker_cycles = 0
        return None, effective_limit
