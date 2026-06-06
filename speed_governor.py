#!/usr/bin/env python3
"""
SpeedGovernor — Lógica de control de velocidad.

Decide qué acción tomar (ACCELERATE / COAST / BRAKE / HOLD) en función de
velocidad actual, límites, gradiente y paradas programadas.
Aplica la acción enviando teclas al juego mediante ThrottleController / BrakeController.
"""

import logging
import time
from typing import Optional

from throttle_controller import ThrottleController
from brake_controller import BrakeController
from tsw_keys import VK_A, VK_D, KEY_HOLD_MS, send_key

# Importaciones modularizadas
from governor_constants import (
    SAFETY_MARGIN, RATE_TOLERANCE, SERVICE_MAX_BRAKE,
    CONTROL_INTERVAL, CONTROL_INTERVAL_BRAKE, CONTROL_INTERVAL_EMERG,
    STATION_STOPPED_MPH, NOTCH_NEUTRAL,
)
from governor_physics import TrainPhysics
from governor_station import StationFSM
from braking_advisor import BrakingAdvisor

_gov_log = logging.getLogger("tsw.governor")


class SpeedGovernor:
    """
    Algoritmo proporcional para mantener velocidad y frenar
    anticipadamente ante reducciones de límite o paradas en estación.
    """

    def __init__(self, target_mph: float = 0.0):
        self.target_mph   = target_mph
        self.throttle     = ThrottleController()
        self.brake        = BrakeController()
        self.last_action  = "HOLD"
        self.last_control = time.time()
        self.paused       = False

        # Instanciar submódulos físicos y de estación
        self._physics = TrainPhysics()
        self._fsm     = StationFSM()
        self._braking = BrakingAdvisor()

        # Seguimiento de atascos en el mando
        self._accel_stuck_count: int = 0
        self._last_accel_notch: Optional[int] = None

        # Seguimiento de ack para detectar la transición ack→libre
        self._ack_was_required: bool = False
        self._ack_approach_warned: bool = False  # aviso previo al ACK (1 vez)

        # P3: Anti-oscilación (banda muerta de 2 ciclos antes de cambiar dirección)
        self._p3_last_direction: Optional[str] = None  # "up" | "down" | None
        self._p3_direction_hold: int = 0  # ciclos restantes de banda muerta

        # Último effective_limit calculado (para logging externo)
        self.effective_limit: float = 0.0

    # ── Redirección de propiedades físicas (Compatibilidad retroactiva) ──────

    @property
    def learner(self):
        return self._physics.learner

    @property
    def max_decel_ms2(self) -> float:
        return self._physics.max_decel_ms2

    @max_decel_ms2.setter
    def max_decel_ms2(self, val: float):
        self._physics.max_decel_ms2 = val

    @property
    def target_decel_ms2(self) -> float:
        return self._physics.target_decel_ms2

    @target_decel_ms2.setter
    def target_decel_ms2(self, val: float):
        self._physics.target_decel_ms2 = val

    @property
    def target_accel_ms2(self) -> float:
        return self._physics.target_accel_ms2

    @target_accel_ms2.setter
    def target_accel_ms2(self, val: float):
        self._physics.target_accel_ms2 = val

    @property
    def coast_decel_ms2(self) -> float:
        return self._physics.coast_decel_ms2

    @coast_decel_ms2.setter
    def coast_decel_ms2(self, val: float):
        self._physics.coast_decel_ms2 = val

    @property
    def _k_stop(self) -> float:
        return self._physics.eff_k_stop

    @property
    def _api_accel(self) -> Optional[float]:
        return self._physics._api_accel

    @_api_accel.setter
    def _api_accel(self, val: Optional[float]):
        self._physics._api_accel = val

    @property
    def _speed_hist(self) -> list:
        return self._physics._speed_hist

    @_speed_hist.setter
    def _speed_hist(self, val: list):
        self._physics._speed_hist = val

    def feed_learner(self, speed_mph: float, grad_pct: float, accel_ms2: Optional[float]) -> None:
        self._physics.feed_learner(speed_mph, self.current_notch, grad_pct, accel_ms2)

    def set_rain_intensity(self, intensity: float) -> None:
        self._physics.set_rain_intensity(intensity)

    @property
    def _eff_max_decel(self) -> float:
        return self._physics.eff_max_decel

    @property
    def _eff_k_stop(self) -> float:
        return self._physics.eff_k_stop

    # ── Redirección de propiedades de estación (Compatibilidad retroactiva) ──

    @property
    def station_state(self) -> Optional[str]:
        return self._fsm.state

    @station_state.setter
    def station_state(self, val: Optional[str]):
        self._fsm.state = val

    @property
    def station_name(self) -> Optional[str]:
        return self._fsm.name

    @station_name.setter
    def station_name(self, val: Optional[str]):
        self._fsm.name = val

    @property
    def _creep_to_station(self) -> bool:
        return self._fsm._creep_to_station

    @_creep_to_station.setter
    def _creep_to_station(self, val: bool):
        self._fsm._creep_to_station = val

    @property
    def target_stop_min_m(self) -> Optional[float]:
        return self._fsm.target_stop_min_m

    @target_stop_min_m.setter
    def target_stop_min_m(self, val: Optional[float]):
        self._fsm.target_stop_min_m = val

    @property
    def _locked_stop_name(self) -> Optional[str]:
        return self._fsm._locked_stop_name

    @_locked_stop_name.setter
    def _locked_stop_name(self, val: Optional[str]):
        self._fsm._locked_stop_name = val

    @property
    def _doors_opened(self) -> bool:
        return self._fsm._doors_opened

    @_doors_opened.setter
    def _doors_opened(self, val: bool):
        self._fsm._doors_opened = val

    @property
    def _stopped_at(self) -> float:
        return self._fsm._stopped_at

    @_stopped_at.setter
    def _stopped_at(self, val: float):
        self._fsm._stopped_at = val

    @property
    def _we_stopped(self) -> bool:
        return self._fsm._we_stopped

    @_we_stopped.setter
    def _we_stopped(self, val: bool):
        self._fsm._we_stopped = val

    @property
    def _min_stop_dist(self) -> Optional[float]:
        return self._fsm._min_stop_dist

    @_min_stop_dist.setter
    def _min_stop_dist(self, val: Optional[float]):
        self._fsm._min_stop_dist = val

    @property
    def _ocr_offset(self) -> Optional[float]:
        return self._fsm._ocr_offset

    @_ocr_offset.setter
    def _ocr_offset(self, val: Optional[float]):
        self._fsm._ocr_offset = val

    @property
    def _ocr_used(self) -> bool:
        return self._fsm._ocr_used

    @_ocr_used.setter
    def _ocr_used(self, val: bool):
        self._fsm._ocr_used = val

    @property
    def _last_departed_name(self) -> Optional[str]:
        return self._fsm._last_departed_name

    @_last_departed_name.setter
    def _last_departed_name(self, val: Optional[str]):
        self._fsm._last_departed_name = val

    @property
    def _last_departed_at(self) -> float:
        return self._fsm._last_departed_at

    @_last_departed_at.setter
    def _last_departed_at(self, val: float):
        self._fsm._last_departed_at = val

    # ── Métodos de delegación rápida ──────────────────────────────────────────

    def record_speed(self, speed_mph: float) -> None:
        self._physics.record_speed(speed_mph)

    @property
    def acceleration_ms2(self) -> Optional[float]:
        return self._physics.acceleration_ms2

    @property
    def g_force(self) -> Optional[float]:
        return self._physics.g_force

    def braking_distance(self, from_mph: float, to_mph: float,
                         decel: Optional[float] = None,
                         margin: float = SAFETY_MARGIN,
                         gradient_pct: Optional[float] = None,
                         current_accel_ms2: Optional[float] = None) -> float:
        return self._physics.braking_distance(
            from_mph, to_mph, decel, margin, gradient_pct, current_accel_ms2
        )

    def should_brake_for_next(self, speed_mph: float,
                               next_limit_mph: Optional[float],
                               distance_m: Optional[float],
                               gradient_pct: Optional[float] = None,
                               react_s: float = 0.0,
                               current_accel_ms2: Optional[float] = None) -> bool:
        return self._physics.should_brake_for_next(
            speed_mph, next_limit_mph, distance_m, gradient_pct, react_s, current_accel_ms2
        )

    # ── Propiedades de notch ─────────────────────────────────────────────────

    @property
    def throttle_notch(self) -> int:
        return self.throttle.notch

    @property
    def brake_notch(self) -> int:
        return self.brake.notch

    @property
    def current_notch(self) -> int:
        """Posición equivalente 0-8 del handle combinado."""
        return NOTCH_NEUTRAL + self.throttle.notch - self.brake.notch

    # ── Decisión de control ──────────────────────────────────────────────────

    def decide(self, speed_mph: float, limit_mph: float,
               next_limit_mph: Optional[float],
               distance_next_m: Optional[float],
               brake_marker_m: Optional[float] = None,
               gradient_pct: Optional[float] = None,
               stations: Optional[list] = None,
               doors_open: bool = False,
               ack_required: bool = False,
               ocr_stop_dist_m: Optional[float] = None,
               ocr_task: Optional[str] = None,
               doors_dmi: Optional[bool] = None,
               supervision: str = "csm",
               speed_limits_ahead: Optional[list] = None) -> str:
        """
        Devuelve una acción: 'ACCELERATE' | 'HOLD' | 'COAST' | 'BRAKE' | 'HARDBRAKE'
        Control proporcional con compensación de gradiente y paradas en estación.
        """
        if self.paused:
            return "PAUSED"

        # Registrar velocidad para el cálculo dv/dt (fallback)
        self.record_speed(speed_mph)

        # ── Aviso pre-ACK ────────────────────────────────────────────────────
        if (not ack_required
                and not self._ack_approach_warned
                and limit_mph is not None
                and speed_mph > limit_mph + 1.0):
            _gov_log.warning(
                "⚠ PRE-ACK  spd=%.1f  lim=%.1f  exceso=+%.1f mph — "
                "el ATP puede intervenir pronto",
                speed_mph, limit_mph, speed_mph - limit_mph)
            self._ack_approach_warned = True

        # ── ACK: supervisión ATP activa ──────────────────────────────────────
        if ack_required:
            if not self._ack_was_required:
                _gov_log.warning("ACK requerido – cediendo control al ATP  spd=%.1f", speed_mph)
                self.brake.notch = 0
                self._ack_was_required = True
            if limit_mph is not None:
                self.effective_limit = limit_mph
            self.last_action = "HOLD"

            if self.throttle.notch > 0:
                return "COAST"
            if limit_mph is not None and speed_mph > limit_mph + 1.0:
                return "BRAKE"
            if (self.brake.is_active
                    and self.station_state != "APPROACHING"
                    and limit_mph is not None and speed_mph <= limit_mph - 2.0):
                return "ACCELERATE"
            return "HOLD"

        # Transición ack→libre
        if self._ack_was_required:
            self._ack_was_required    = False
            self._ack_approach_warned = False
            _gov_log.info("ACK liberado – retomando control  fsm=%s  spd=%.1f",
                          self.station_state or "-", speed_mph)
            if self.station_state == "APPROACHING":
                self._fsm.state = None
                self._fsm.name  = None
                self._fsm._min_stop_dist = None
                self._fsm._ocr_offset    = None
                self._fsm._ocr_used      = False
                _gov_log.info("FSM reset: APPROACHING → None  (post-ATP)")

        # ── Actualizar FSM de paradas en estación ────────────────────────────
        action_override, eff_limit_override = self._fsm.update_state_transitions(
            speed_mph=speed_mph,
            limit_mph=limit_mph,
            stations=stations,
            doors_open=doors_open,
            doors_dmi=doors_dmi,
            ocr_stop_dist_m=ocr_stop_dist_m,
            ocr_task=ocr_task,
            braking_dist_fn=self.braking_distance,
            eff_max_decel=self._eff_max_decel,
            eff_k_stop=self._eff_k_stop
        )

        if action_override is not None:
            self.effective_limit = eff_limit_override or 0.0
            return action_override

        # Límite por defecto (crucero)
        effective_limit = (min(limit_mph, self.target_mph)
                           if self.target_mph > 0 else limit_mph)

        # Si estamos en APPROACHING pero el FSM no forzó acción (por ejemplo, perfil rampa)
        if self.station_state == "APPROACHING" and eff_limit_override is not None:
            effective_limit = eff_limit_override

        # ── Marcador de freno advisory (DMI) ────────────────────────────────────
        if (brake_marker_m is not None
                and limit_mph is not None
                and speed_mph > limit_mph - 1.0):
            bm_bd = self.braking_distance(speed_mph, limit_mph, gradient_pct=gradient_pct)
            if brake_marker_m <= bm_bd:
                effective_limit = min(effective_limit, limit_mph)
            if (brake_marker_m <= max(50.0, bm_bd * 0.25)
                    and speed_mph > limit_mph + 1.0):
                _gov_log.warning(
                    "Marcador freno HARDBRAKE  spd=%.1f  lim=%.1f  "
                    "marker=%.0fm  bd=%.0fm",
                    speed_mph, limit_mph, brake_marker_m, bm_bd)
                return "HARDBRAKE"
            if brake_marker_m <= bm_bd * 0.6 and speed_mph > limit_mph:
                if self.throttle.notch > 0:
                    return "COAST"
                return "BRAKE"

        # ── P1: Frenado anticipado al próximo límite de velocidad ───────────────
        _p1_active = (self.station_state not in ("APPROACHING", "DEPARTING")
                      or speed_mph > 10.0)
        if not _p1_active:
            self._braking.reset()
        else:
            p1_action, effective_limit = self._braking.evaluate(
                speed_mph=speed_mph,
                next_limit_mph=next_limit_mph,
                distance_next_m=distance_next_m,
                effective_limit=effective_limit,
                gradient_pct=gradient_pct,
                acceleration_ms2=self.acceleration_ms2,
                braking_distance_fn=self.braking_distance,
                should_brake_fn=self.should_brake_for_next,
                eff_k_stop=self._eff_k_stop,
                throttle_notch=self.throttle.notch,
                speed_limits_ahead=speed_limits_ahead,
            )
            if p1_action is not None:
                self.effective_limit = effective_limit
                return p1_action

        self.effective_limit = effective_limit
        error = effective_limit - speed_mph

        # ── P2-MEJORADO: Control con histéresis adaptativa ───────────────────────
        # Bandas adaptativas por lluvia y pendiente
        _rain = self._physics._rain_intensity
        _band_narrow = 1.0
        if gradient_pct is not None and gradient_pct < -0.5:
            _band_narrow = 0.7  # bandas más estrechas en bajada
        _rain_offset_servicio = 1.0 if _rain > 0.3 else 0.0
        _rain_offset_critico  = 2.0 if _rain > 0.3 else 0.0

        # Detección de gradiente crítico → forzar MAX_BRAKE
        if (error < 0 and gradient_pct is not None
                and self._physics.is_critical_gradient(gradient_pct)
                and speed_mph > effective_limit + 1.0):
            _gov_log.warning(
                "P2 GRADIENTE CRITICO  spd=%.1f  elim=%.1f  grad=%.1f%%  → HARDBRAKE",
                speed_mph, effective_limit, gradient_pct)
            return "HARDBRAKE"

        # OVER-CRITICO por límite de vía: speed > limit + umbral → HARDBRAKE
        # (independiente del error por effective_limit, compara con limit_mph real)
        if (limit_mph is not None
                and self.station_state not in ("APPROACHING", "STOPPED")):
            _over_crit = (3.0 - _rain_offset_critico) * _band_narrow
            if speed_mph > limit_mph + _over_crit:
                _gov_log.warning(
                    "P2 OVER-CRITICO  spd=%.1f  lim=%.1f  umbral=+%.1f",
                    speed_mph, limit_mph, _over_crit)
                return "HARDBRAKE"

        # P2: Crucero pegado al límite de vía
        if (error >= 0 and limit_mph is not None
                and self.station_state not in ("APPROACHING", "STOPPED")):
            if speed_mph > limit_mph:
                if self.throttle.notch > 0:
                    return "COAST"
                return "BRAKE"
            if speed_mph > limit_mph - 0.5 and self.throttle.notch > 0:
                return "COAST"

        # ── P2: Overspeed (por effective_limit o límite) ───────────────────────
        if error < 0:
            if self.station_state == "APPROACHING":
                if self.throttle.notch > 0:
                    return "COAST"
                a = self.acceleration_ms2
                if (effective_limit == 0.0
                        and speed_mph <= STATION_STOPPED_MPH + 1.0):
                    return "HOLD"
                if effective_limit == 0.0:
                    v_ms  = speed_mph * 0.44704
                    d_m   = max(self._min_stop_dist or 1.0, 1.0)
                    a_need = (v_ms ** 2) / (2.0 * d_m)
                    a_now  = -(a if a is not None else 0.0)
                    if a_now < a_need * 0.85:
                        _gov_log.info(
                            "P2 FULLSTOP  spd=%.1f  d=%.1fm  need=%.2f  now=%.2f  ocr=%s",
                            speed_mph, d_m, a_need, a_now,
                            "si" if self._ocr_used else "no")
                        return "FULLSTOP"
                    if (a_now > max(a_need * 1.6, self.max_decel_ms2)
                            and self.brake.is_active):
                        return "ACCELERATE"
                    return "HOLD"
                else:
                    _brake_cond = (a is None
                                   or a > -(self.target_decel_ms2 - RATE_TOLERANCE))
                    if error < -8.0 or _brake_cond:
                        _gov_log.info(
                            "P2 BRAKE (APPROACHING)  spd=%.1f  elim=%.1f  err=%.1f  a=%s",
                            speed_mph, effective_limit, error,
                            f"{a:.2f}" if a is not None else "?")
                        return "BRAKE"
                    if (a is not None
                            and a < -(self.target_decel_ms2 + RATE_TOLERANCE)
                            and self.brake.is_active):
                        return "ACCELERATE"
                    return "HOLD"

            if self.throttle.notch > 0:
                return "COAST"
            _a = self.acceleration_ms2
            _decel_ok = (_a is not None and _a <= -self.target_decel_ms2 + RATE_TOLERANCE)

            # Bandas adaptativas para overspeed
            _over_serv = (0.5 + _rain_offset_servicio) * _band_narrow
            # OVER-CRITICO by effective_limit uses a higher threshold (5 mph)
            # because effective_limit may be a gradual P1 profile, not a hard limit.
            # Reserve aggressive HARDBRAKE for the track limit (handled above).
            _over_crit_elim = 5.0 - _rain_offset_critico

            # OVER-CRITICO (por effective_limit) — solo emergencia extrema
            if -error > _over_crit_elim:
                if not _decel_ok:
                    _gov_log.warning(
                        "P2 OVER-CRITICO (elim)  spd=%.1f  elim=%.1f  err=%.1f",
                        speed_mph, effective_limit, error)
                    return "HARDBRAKE"

            # TSM/overspeed: COAST→BRAKE inmediato (banda OVER-LEVE desaparece)
            if supervision in ("tsm", "overspeed") and speed_mph > limit_mph - 1.5:
                if _decel_ok:
                    return "HOLD"
                _gov_log.info(
                    "P2 BRAKE (tsm/overspeed)  spd=%.1f  lim=%.1f  sup=%s",
                    speed_mph, limit_mph, supervision)
                return "BRAKE"
            if gradient_pct is not None and gradient_pct < -0.5:
                if speed_mph > effective_limit:
                    if _decel_ok:
                        return "HOLD"
                    _gov_log.info(
                        "P2 BRAKE (bajada)  spd=%.1f  elim=%.1f  grad=%.1f%%",
                        speed_mph, effective_limit, gradient_pct)
                    return "BRAKE"
                if self.throttle.notch > 0:
                    return "COAST"
                return "HOLD"
            return "HOLD"

        # ── Liberar freno residual (de P1 o parada) antes de continuar ───────────
        if self.brake.is_active:
            if (self.station_state == "STOPPED"
                    or (self.station_state == "APPROACHING"
                        and speed_mph <= STATION_STOPPED_MPH + 1.0
                        and self.effective_limit <= 1.0)):
                if self.station_state != "DEPARTING":
                    return "HOLD"
            return "ACCELERATE"

        # ── En APPROACHING con velocidad por debajo del perfil: no acelerar ─────────
        if self.station_state == "APPROACHING" and not self._creep_to_station:
            a = self.acceleration_ms2
            if self.throttle.notch > 0 and (a is None or a > 0.15):
                return "COAST"
            return "HOLD"

        # ── P3-MEJORADO: Protocolo de aceleración — control por tasa adaptativo ──
        if self.station_state == "STOPPED" or (self.station_state == "APPROACHING" and not self._creep_to_station):
            return "HOLD"

        # Crucero (error <= 1.5 mph): mantener velocidad
        if error <= 1.5:
            a = self.acceleration_ms2
            if error <= -0.3:
                if self.throttle.notch > 0 and (a is None or a > 0.15):
                    return "COAST"
                return "HOLD"
            if self.throttle.notch > 0 and (a is None or a > 0.30):
                return "COAST"
            if a is not None and a < -0.05 and not self.brake.is_active:
                return "ACCELERATE"
            return "HOLD"

        # Fase de aceleración (error > 1.5 mph):
        a = self.acceleration_ms2

        # P3-MEJORADO: Compensación de gradiente en target_accel
        _target_accel = self.target_accel_ms2
        if gradient_pct is not None:
            # En subida: necesita más aceleración; en bajada: menos
            _target_accel = _target_accel + 9.81 * (gradient_pct / 100.0)
            _target_accel = max(_target_accel, 0.05)  # suelo mínimo

        # P3-MEJORADO: Rampa de arranque (primeros 5 mph → 60% del target)
        if speed_mph < 5.0:
            _target_accel *= 0.60

        # P3-MEJORADO: Techo por proximidad a límite (error < 3 mph → max 0.15 m/s²)
        if error < 3.0:
            _target_accel = min(_target_accel, 0.15)

        if a is not None:
            if speed_mph < 1.0 and a < 0.1:
                target_t = max(2, min(self.throttle.notch + 1, 3))
            elif a < _target_accel - RATE_TOLERANCE:
                target_t = min(self.throttle.notch + 1, ThrottleController.MAX_NOTCH)
            elif a > _target_accel + RATE_TOLERANCE:
                target_t = max(self.throttle.notch - 1, 0)
            else:
                target_t = self.throttle.notch
            
            if error > 15.0:
                target_t = max(target_t, 3)
            elif error > 8.0:
                target_t = max(target_t, 2)

            if error <= 4.0:
                target_t = min(target_t, 1)
            elif error <= 8.0:
                target_t = min(target_t, 2)
            elif error <= 12.0:
                target_t = min(target_t, 3)
        else:
            if error > 15.0:
                target_t = 4
            elif error > 8.0:
                target_t = 3
            elif error > 4.0:
                target_t = 2
            else:
                target_t = 1
            if gradient_pct is not None:
                if gradient_pct > 0.5:
                    target_t = min(target_t + 1, ThrottleController.MAX_NOTCH)
                elif gradient_pct < -1.0:
                    target_t = max(target_t - 1, 0)

        # P3-MEJORADO: Anti-oscilación (banda muerta de 2 ciclos)
        if self.throttle.notch > target_t:
            _new_dir = "down"
        elif self.throttle.notch < target_t:
            _new_dir = "up"
        else:
            _new_dir = None
            self._p3_direction_hold = 0

        if _new_dir is not None and self._p3_last_direction is not None:
            if _new_dir != self._p3_last_direction:
                if self._p3_direction_hold < 2:
                    self._p3_direction_hold += 1
                    return "HOLD"  # banda muerta: esperar antes de cambiar
                self._p3_direction_hold = 0

        self._p3_last_direction = _new_dir

        if self.throttle.notch > target_t:
            return "COAST"
        if self.throttle.notch < target_t and not self.brake.is_active:
            return "ACCELERATE"
        return "HOLD"

    # ── Aplicar acción ───────────────────────────────────────────────────────

    def apply_action(self, action: str, hwnd: Optional[int], conn=None) -> bool:
        """Aplica la acción enviando teclas al juego. Devuelve True si actuó."""
        if action in ("HOLD", "PAUSED"):
            self.last_action = action
            return False

        now = time.time()
        if action == "ACCELERATE":
            interval = CONTROL_INTERVAL
        elif action == "HARDBRAKE":
            interval = CONTROL_INTERVAL_EMERG
        elif action in ("COAST", "BRAKE", "FULLSTOP"):
            interval = CONTROL_INTERVAL_BRAKE
        else:
            interval = CONTROL_INTERVAL
        if now - self.last_control < interval:
            return False

        self.last_action = action

        # Detección de mando atascado al acelerar
        if action == "ACCELERATE":
            current_combined_notch = self.throttle.notch - self.brake.notch
            if self._last_accel_notch == current_combined_notch:
                self._accel_stuck_count += 1
                if self._accel_stuck_count >= 4:
                    _gov_log.warning("Mando atascado al intentar acelerar. Forzando reset a neutro.")
                    self.force_neutral(hwnd)
                    self._accel_stuck_count = 0
                    self.last_control = now
                    return True
            else:
                self._accel_stuck_count = 0
            self._last_accel_notch = current_combined_notch
        else:
            self._accel_stuck_count = 0
            self._last_accel_notch = None

        if action == "ACCELERATE":
            if self.brake.is_active:
                self.brake.release(hwnd)
                self.last_control = now
                return True
            if self._ack_was_required:
                return False
            if self.throttle.accelerate(hwnd):
                self.last_control = now
                return True

        elif action == "COAST":
            if self.throttle.is_active:
                self.throttle.coast(hwnd)
                self.last_control = now
                return True

        elif action == "HARDBRAKE":
            acted = False
            if self.throttle.is_active:
                self.throttle.coast(hwnd)
                acted = True
            steps = 2
            actual = min(steps, SERVICE_MAX_BRAKE - self.brake.notch)
            if actual > 0:
                self.brake.apply(hwnd, steps=actual)
                acted = True
            if acted:
                self.last_control = now
                return True

        elif action in ("BRAKE", "FULLSTOP"):
            if self.throttle.is_active:
                self.throttle.coast(hwnd)
                self.last_control = now
                return True
            if action == "FULLSTOP":
                steps = 1
                max_b = BrakeController.MAX_NOTCH
            else:
                steps = 1
                max_b = SERVICE_MAX_BRAKE
            actual = min(steps, max_b - self.brake.notch)
            if actual > 0 and self.brake.apply(hwnd, steps=actual):
                self.last_control = now
                return True

        return False

    def reset_neutral(self, hwnd: Optional[int]) -> None:
        """Lleva acelerador y freno a posición neutra."""
        self.throttle.release_all(hwnd)
        self.brake.release_all(hwnd)

    def force_neutral(self, hwnd: Optional[int]) -> None:
        """Sincroniza el handle con el juego desde posición DESCONOCIDA."""
        if hwnd is None:
            return
        _gov_log.warning("force_neutral: sincronizando handle desde posición desconocida…")
        pause = KEY_HOLD_MS / 1000.0 + 0.05
        total_down = ThrottleController.MAX_NOTCH + BrakeController.MAX_NOTCH
        for _ in range(total_down):
            send_key(hwnd, VK_D)
            time.sleep(pause)
        for _ in range(4):
            send_key(hwnd, VK_A)
            time.sleep(pause)
        self.throttle.notch = 0
        self.brake.notch    = 0
        _gov_log.info("force_neutral: handle en neutro (pos 4). Contadores: t=0 b=0")
