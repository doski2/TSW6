#!/usr/bin/env python3
"""
speed_decider.py — Lógica de decisión de velocidad (P1 + P2 + P3 + FSM).

SpeedDecider recibe un TrainState y devuelve una acción de control:
  ACCELERATE | COAST | BRAKE | HARDBRAKE | FULLSTOP | HOLD | PAUSED

Separación de responsabilidades:
  - SpeedDecider: SOLO decide qué hacer, sin saber cómo ejecutarlo
  - HandleController: SOLO ejecuta, sin saber por qué
  - SafetyWatchdog: override de emergencia, sin lógica de crucero

Estado interno permitido:
  - TrainPhysics (acelerómetro, learner)
  - StationFSM (máquina de estados de paradas)
  - BrakingAdvisor (contador de ciclos P1)
  - P3 anti-oscilación (2 variables: last_dir, hold_count)
  - ACK state (2 booleans)

No hay seguimiento de notch interno. Toda la posición del handle se lee
de state.handle_notch (telemetría como fuente de verdad).
"""

import logging
import time
from typing import Optional

from governor_constants import (
    P3_LOOKAHEAD_S, P3_SPEED_TOL_MPH, P3_DEADBAND_CYCLES,
    CONTROL_INTERVAL, P2_LIMIT_BRAKE_THRESHOLD, P2_TSM_BRAKE_THRESHOLD,
    RATE_TOLERANCE, STATION_STOPPED_MPH,
)
from governor_physics import TrainPhysics
from braking_advisor import BrakingAdvisor
from governor_station import StationFSM
from train_state import TrainState

_log = logging.getLogger("tsw.governor")

# Número máximo de notch de tracción en el half-handle (0-4)
_MAX_THROTTLE_NOTCH = 4


class SpeedDecider:
    """
    Capa de decisión del autopilot: recibe TrainState, devuelve acción.

    Exposición pública de atributos para el dashboard (compatibilidad duck-typing):
      - target_mph, last_action, paused
      - effective_limit
      - station_state, station_name
      - acceleration_ms2, g_force, _api_accel
      - throttle_notch, brake_notch, current_notch
      - braking_distance(), should_brake_for_next()
      - target_stop_min_m, _locked_stop_name, _creep_to_station
    """

    def __init__(self, target_mph: float = 0.0) -> None:
        self._physics   = TrainPhysics()
        self._fsm       = StationFSM()
        self._braking   = BrakingAdvisor()

        # Configuración del operador
        self.target_mph: float = target_mph
        self.paused:     bool  = False

        # P3 anti-oscilación
        self._p3_last_direction: Optional[str] = None
        self._p3_direction_hold: int           = 0

        # ACK (ATP activo)
        self._ack_was_required:    bool  = False
        self._ack_approach_warned: bool  = False
        self._ack_started_t:       float = 0.0   # monotonico: cuando empezó ACK
        self._ack_last_warn_t:     float = 0.0   # última vez que avisamos

        # Estado público para logging / dashboard
        self.effective_limit: float = 0.0
        self.last_action:     str   = "HOLD"

        # Caché del último TrainState visto (para propiedades de dashboard)
        self._last_state: Optional[TrainState] = None

    # ── Physics API (llamar antes de decide() cada ciclo) ─────────────────

    def update_physics(self, speed_mph: float,
                       api_accel: Optional[float],
                       gradient_pct: float = 0.0) -> None:
        """Actualiza el acelerómetro y el learner con los datos del ciclo."""
        self._physics.record_speed(speed_mph)
        if api_accel is not None:
            self._physics._api_accel = api_accel

    def feed_learner(self, speed_mph: float, handle_notch: int,
                     gradient_pct: float, accel_ms2: Optional[float]) -> None:
        """Alimenta el aprendiz online. Llamar una vez por ciclo."""
        throttle_n = max(0, handle_notch - 4)  # solo zona de tracción
        self._physics.feed_learner(speed_mph, throttle_n, gradient_pct, accel_ms2)

    def set_rain_intensity(self, intensity: float) -> None:
        self._physics.set_rain_intensity(intensity)

    # ── Propiedades delegadas para el dashboard ────────────────────────────

    @property
    def acceleration_ms2(self) -> Optional[float]:
        return self._physics.acceleration_ms2

    @property
    def g_force(self) -> Optional[float]:
        return self._physics.g_force

    @property
    def _api_accel(self) -> Optional[float]:
        return self._physics._api_accel

    @property
    def station_state(self) -> Optional[str]:
        return self._fsm.state

    @property
    def station_name(self) -> Optional[str]:
        return self._fsm.name

    @property
    def target_stop_min_m(self) -> Optional[float]:
        return self._fsm.target_stop_min_m

    @target_stop_min_m.setter
    def target_stop_min_m(self, value: Optional[float]) -> None:
        self._fsm.target_stop_min_m = value

    @property
    def _locked_stop_name(self) -> Optional[str]:
        return self._fsm._locked_stop_name

    @_locked_stop_name.setter
    def _locked_stop_name(self, value: Optional[str]) -> None:
        self._fsm._locked_stop_name = value

    @property
    def _creep_to_station(self) -> bool:
        return self._fsm._creep_to_station

    @property
    def throttle_notch(self) -> int:
        """Notch de tracción actual según último state visto."""
        if self._last_state is not None:
            return self._last_state.throttle_notch
        return 0

    @property
    def brake_notch(self) -> int:
        """Notch de freno actual según último state visto."""
        if self._last_state is not None:
            return self._last_state.brake_notch
        return 0

    @property
    def current_notch(self) -> int:
        """Handle combinado (0-8) según último state visto."""
        if self._last_state is not None:
            return self._last_state.handle_notch
        return 4

    # ── Delegados de physics para el dashboard ─────────────────────────────

    def braking_distance(self, from_mph: float, to_mph: float,
                         **kwargs) -> float:
        return self._physics.braking_distance(from_mph, to_mph, **kwargs)

    def should_brake_for_next(self, *args, **kwargs) -> bool:
        return self._physics.should_brake_for_next(*args, **kwargs)

    @property
    def max_decel_ms2(self) -> float:
        return self._physics.max_decel_ms2

    @property
    def target_decel_ms2(self) -> float:
        return self._physics.target_decel_ms2

    @property
    def _eff_max_decel(self) -> float:
        return self._physics.eff_max_decel

    @property
    def _eff_k_stop(self) -> float:
        return self._physics.eff_k_stop

    @property
    def _min_stop_dist(self) -> Optional[float]:
        return self._fsm._min_stop_dist

    @property
    def _ocr_used(self) -> bool:
        return self._fsm._ocr_used

    # ── Decisión principal ────────────────────────────────────────────────

    def decide(self, state: TrainState) -> str:
        """
        Decide la acción de control para el ciclo actual.

        Capas de prioridad (mayor a menor):
          ACK (ATP) → FSM estación → P1 (frenado anticipado) → P2 (crucero/overspeed) → P3 (aceleración)

        Garantía: siempre devuelve una de:
          ACCELERATE | COAST | BRAKE | HARDBRAKE | FULLSTOP | HOLD | PAUSED
        """
        self._last_state = state

        if state.paused:
            self.last_action = "PAUSED"
            return "PAUSED"

        speed   = state.speed_mph
        limit   = state.limit_mph
        grad    = state.gradient_pct
        a       = state.acceleration_ms2  # puede ser None

        # Atajos locales (reducen ruido visual en el código)
        th_n    = state.throttle_notch     # 0-4
        th_act  = state.throttle_active
        br_act  = state.brake_active
        sup     = state.supervision

        # ── Aviso pre-ACK ─────────────────────────────────────────────────
        if (not state.ack_required
                and not self._ack_approach_warned
                and speed > limit + 1.0):
            _log.warning(
                "PRE-ACK  spd=%.1f  lim=%.1f  exceso=+%.1f mph",
                speed, limit, speed - limit)
            self._ack_approach_warned = True

        # ── ACK: supervisión ATP activa ───────────────────────────────────
        # Durante ACK el ATP tiene control total. Solo:
        #   - COAST si hay tracción activa (liberar la maneta al neutro)
        #   - HOLD en todo lo demás (no interferir con el frenado del ATP)
        # No enviamos ACCELERATE para liberar frenos: el companion o el ATP
        # pueden estar frenando intencionadamente (ej. parada en estación) y
        # el ACCELERATE genera un bucle companion-boost→COAST-suprimido→decel.
        if state.ack_required:
            now_t = time.monotonic()
            if not self._ack_was_required:
                _log.warning(
                    "ACK requerido – cediendo control al ATP  spd=%.1f", speed)
                self._ack_was_required = True
                self._ack_started_t    = now_t
                self._ack_last_warn_t  = now_t

            # Aviso cada 15 s cuando el tren está parado y el ACK no se libera
            elif (speed <= 0.5
                  and now_t - self._ack_last_warn_t >= 15.0):
                elapsed = now_t - self._ack_started_t
                _log.warning(
                    "ACK lleva %.0fs activo con tren parado — "
                    "confirma la alerta en el DMI o en RailBridge Companion "
                    "(botón ACK / Acknowledge) para que el autopilot pueda salir.",
                    elapsed)
                self._ack_last_warn_t = now_t

            self.effective_limit = limit
            self.last_action = "HOLD"

            if th_act:
                self.last_action = "COAST"
                return "COAST"
            return "HOLD"

        # Transición ack → libre
        if self._ack_was_required:
            self._ack_was_required    = False
            self._ack_approach_warned = False
            elapsed_ack = time.monotonic() - self._ack_started_t
            _log.info(
                "ACK liberado tras %.0fs – retomando control  fsm=%s  spd=%.1f",
                elapsed_ack, state.station_state or "-", speed)
            if state.station_state == "APPROACHING":
                self._fsm.state            = None
                self._fsm.name             = None
                self._fsm._min_stop_dist   = None
                self._fsm._ocr_offset      = None
                self._fsm._ocr_used        = False
                _log.info("FSM reset: APPROACHING → None  (post-ATP)")

        # ── FSM de paradas en estación ────────────────────────────────────
        stations_list = list(state.stations) if state.stations else None
        speed_lims_list = list(state.speed_limits_ahead) if state.speed_limits_ahead else None

        action_override, eff_limit_override = self._fsm.update_state_transitions(
            speed_mph       = speed,
            limit_mph       = limit,
            stations        = stations_list,
            doors_open      = state.doors_open,
            doors_dmi       = state.doors_dmi,
            ocr_stop_dist_m = state.ocr_stop_dist_m,
            ocr_task        = state.ocr_task,
            braking_dist_fn = self._physics.braking_distance,
            eff_max_decel   = self._physics.eff_max_decel,
            eff_k_stop      = self._physics.eff_k_stop,
        )

        if action_override is not None:
            self.effective_limit = eff_limit_override or 0.0
            self.last_action = action_override
            return action_override

        # Límite efectivo de crucero
        effective_limit = (min(limit, state.target_mph)
                           if state.target_mph > 0 else limit)

        if state.station_state == "APPROACHING" and eff_limit_override is not None:
            effective_limit = eff_limit_override

        # ── Marcador de freno advisory (DMI) ─────────────────────────────
        bm = state.brake_marker_m
        if bm is not None and speed > limit - 1.0:
            bm_bd = self._physics.braking_distance(speed, limit, gradient_pct=grad)
            if bm <= bm_bd:
                effective_limit = min(effective_limit, limit)
            if bm <= max(50.0, bm_bd * 0.25) and speed > limit + 1.0:
                _log.warning(
                    "Marcador freno HARDBRAKE  spd=%.1f  lim=%.1f  "
                    "marker=%.0fm  bd=%.0fm",
                    speed, limit, bm, bm_bd)
                act = "HARDBRAKE"
                self.effective_limit = effective_limit
                self.last_action = act
                return act
            if bm <= bm_bd * 0.6 and speed > limit:
                act = "COAST" if th_act else "BRAKE"
                self.effective_limit = effective_limit
                self.last_action = act
                return act

        # ── P1: Frenado anticipado al próximo límite ──────────────────────
        _p1_active = (state.station_state not in ("APPROACHING", "DEPARTING")
                      or speed > 10.0)
        if not _p1_active:
            self._braking.reset()
        else:
            p1_action, effective_limit = self._braking.evaluate(
                speed_mph          = speed,
                next_limit_mph     = state.next_limit_mph,
                distance_next_m    = state.distance_next_m,
                effective_limit    = effective_limit,
                gradient_pct       = grad,
                acceleration_ms2   = a,
                braking_distance_fn= self._physics.braking_distance,
                should_brake_fn    = self._physics.should_brake_for_next,
                eff_k_stop         = self._physics.eff_k_stop,
                throttle_notch     = th_n,
                speed_limits_ahead = speed_lims_list,
            )
            if p1_action is not None:
                self.effective_limit = effective_limit
                self.last_action = p1_action
                return p1_action

        self.effective_limit = effective_limit
        error = effective_limit - speed

        # ── P2: Control con histéresis adaptativa ─────────────────────────
        _rain         = self._physics._rain_intensity
        _band_narrow  = 0.7 if grad < -0.5 else 1.0
        _rain_serv    = 1.0 if _rain > 0.3 else 0.0
        _rain_crit    = 2.0 if _rain > 0.3 else 0.0

        # Gradiente crítico → HARDBRAKE
        if (error < 0
                and self._physics.is_critical_gradient(grad)
                and speed > effective_limit + 1.0):
            _log.warning(
                "P2 GRADIENTE CRITICO  spd=%.1f  elim=%.1f  grad=%.1f%%  → HARDBRAKE",
                speed, effective_limit, grad)
            act = "HARDBRAKE"
            self.last_action = act
            return act

        # Exceso crítico sobre límite de vía real → HARDBRAKE
        if state.station_state not in ("APPROACHING", "STOPPED"):
            _over_crit = (3.0 - _rain_crit) * _band_narrow
            if speed > limit + _over_crit:
                _log.warning(
                    "P2 OVER-CRITICO  spd=%.1f  lim=%.1f  umbral=+%.1f",
                    speed, limit, _over_crit)
                act = "HARDBRAKE"
                self.last_action = act
                return act

        # Crucero pegado al límite
        if (error >= 0
                and state.station_state not in ("APPROACHING", "STOPPED")):
            _p2_excess = speed - limit
            if _p2_excess >= P2_LIMIT_BRAKE_THRESHOLD:
                act = "COAST" if th_act else "BRAKE"
                self.last_action = act
                return act
            if _p2_excess > 0.0:
                act = "COAST" if th_act else "HOLD"
                self.last_action = act
                return act
            if speed > limit - 0.5 and th_act:
                self.last_action = "COAST"
                return "COAST"
            if grad < -0.5 and speed > limit - 2.0 and th_act:
                self.last_action = "COAST"
                return "COAST"

        # P2 Overspeed
        if error < 0:
            if state.station_state == "APPROACHING":
                if th_act:
                    self.last_action = "COAST"
                    return "COAST"
                if (effective_limit == 0.0
                        and speed <= STATION_STOPPED_MPH + 1.0):
                    self.last_action = "HOLD"
                    return "HOLD"
                if effective_limit == 0.0:
                    v_ms  = speed * 0.44704
                    d_m   = max(self._fsm._min_stop_dist or 1.0, 1.0)
                    a_need = (v_ms ** 2) / (2.0 * d_m)
                    a_now  = -(a if a is not None else 0.0)
                    if a_now < a_need * 0.85:
                        _log.info(
                            "P2 FULLSTOP  spd=%.1f  d=%.1fm  need=%.2f  now=%.2f  ocr=%s",
                            speed, d_m, a_need, a_now,
                            "si" if self._fsm._ocr_used else "no")
                        self.last_action = "FULLSTOP"
                        return "FULLSTOP"
                    if (a is not None
                            and a_now > max(a_need * 1.6, self._physics.max_decel_ms2)
                            and br_act):
                        self.last_action = "ACCELERATE"
                        return "ACCELERATE"
                    self.last_action = "HOLD"
                    return "HOLD"
                else:
                    _brake_cond = (a is None
                                   or a > -(self._physics.target_decel_ms2 - RATE_TOLERANCE))
                    if error < -8.0 or _brake_cond:
                        _log.info(
                            "P2 BRAKE (APPROACHING)  spd=%.1f  elim=%.1f  err=%.1f  a=%s",
                            speed, effective_limit, error,
                            f"{a:.2f}" if a is not None else "?")
                        self.last_action = "BRAKE"
                        return "BRAKE"
                    if (a is not None
                            and a < -(self._physics.target_decel_ms2 + RATE_TOLERANCE)
                            and br_act):
                        self.last_action = "ACCELERATE"
                        return "ACCELERATE"
                    self.last_action = "HOLD"
                    return "HOLD"

            if th_act:
                self.last_action = "COAST"
                return "COAST"

            _decel_ok = (a is not None and a <= -self._physics.target_decel_ms2 + RATE_TOLERANCE)
            _over_serv      = (0.5 + _rain_serv) * _band_narrow
            _over_crit_elim = 5.0 - _rain_crit

            if -error > _over_crit_elim:
                if not _decel_ok:
                    _log.warning(
                        "P2 OVER-CRITICO (elim)  spd=%.1f  elim=%.1f  err=%.1f",
                        speed, effective_limit, error)
                    self.last_action = "HARDBRAKE"
                    return "HARDBRAKE"

            if sup in ("tsm", "overspeed") and speed > limit - 1.5:
                _tsm_excess = speed - limit
                if _tsm_excess < P2_TSM_BRAKE_THRESHOLD:
                    if _tsm_excess > 0 and th_act:
                        self.last_action = "COAST"
                        return "COAST"
                    self.last_action = "HOLD"
                    return "HOLD"
                if _decel_ok:
                    self.last_action = "HOLD"
                    return "HOLD"
                _log.info(
                    "P2 BRAKE (tsm/overspeed)  spd=%.1f  lim=%.1f  sup=%s  exceso=%.1f",
                    speed, limit, sup, _tsm_excess)
                self.last_action = "BRAKE"
                return "BRAKE"

            if grad < -0.5:
                if speed > effective_limit:
                    if _decel_ok:
                        self.last_action = "HOLD"
                        return "HOLD"
                    _log.info(
                        "P2 BRAKE (bajada)  spd=%.1f  elim=%.1f  grad=%.1f%%",
                        speed, effective_limit, grad)
                    self.last_action = "BRAKE"
                    return "BRAKE"
                if th_act:
                    self.last_action = "COAST"
                    return "COAST"
                self.last_action = "HOLD"
                return "HOLD"

            self.last_action = "HOLD"
            return "HOLD"

        # ── Liberar freno residual antes de continuar ─────────────────────
        if br_act:
            if (state.station_state == "STOPPED"
                    or (state.station_state == "APPROACHING"
                        and speed <= STATION_STOPPED_MPH + 1.0
                        and effective_limit <= 1.0)):
                if state.station_state != "DEPARTING":
                    self.last_action = "HOLD"
                    return "HOLD"
            self.last_action = "ACCELERATE"
            return "ACCELERATE"

        # Guardia: no acelerar en APPROACHING sin creep activo
        if state.station_state == "APPROACHING" and not self._fsm._creep_to_station:
            if th_act and (a is None or a > 0.15):
                self.last_action = "COAST"
                return "COAST"
            self.last_action = "HOLD"
            return "HOLD"

        if (state.station_state == "STOPPED"
                or (state.station_state == "APPROACHING"
                    and not self._fsm._creep_to_station)):
            self.last_action = "HOLD"
            return "HOLD"

        # Crucero (error <= 1.5 mph): mantener velocidad sin P3
        if error <= 1.5:
            if error <= -0.3:
                if th_act and (a is None or a > 0.15):
                    self.last_action = "COAST"
                    return "COAST"
                self.last_action = "HOLD"
                return "HOLD"
            if th_act and (a is None or a > 0.30):
                self.last_action = "COAST"
                return "COAST"
            if a is not None and a < -0.05 and not br_act:
                self.last_action = "ACCELERATE"
                return "ACCELERATE"
            self.last_action = "HOLD"
            return "HOLD"

        # ── P3: Control por proyección de velocidad ───────────────────────
        if a is not None:
            v_proj_mph = speed + (a * P3_LOOKAHEAD_S) / 0.44704
            proj_err   = effective_limit - v_proj_mph

            _log.debug(
                "P3 proj  spd=%.1f  a=%.3f  v_proj=%.1f  elim=%.1f  proj_err=%.1f  grad=%.1f%%",
                speed, a, v_proj_mph, effective_limit, proj_err, grad)

            if proj_err > P3_SPEED_TOL_MPH:
                target_t = min(th_n + 1, _MAX_THROTTLE_NOTCH)
            elif proj_err < -P3_SPEED_TOL_MPH:
                target_t = max(th_n - 1, 0)
            else:
                target_t = th_n
        else:
            # Tabla abierta por error + compensación de gradiente (sin acelerómetro)
            if error > 15.0:
                target_t = 4
            elif error > 8.0:
                target_t = 3
            elif error > 4.0:
                target_t = 2
            else:
                target_t = 1
            if grad > 0.5:
                target_t = min(target_t + 1, _MAX_THROTTLE_NOTCH)
            elif grad < -1.0:
                target_t = max(target_t - 1, 0)

        # Anti-oscilación: banda muerta de P3_DEADBAND_CYCLES antes de cambiar dirección
        if th_n > target_t:
            _new_dir: Optional[str] = "down"
        elif th_n < target_t:
            _new_dir = "up"
        else:
            _new_dir = None
            self._p3_direction_hold = 0

        if _new_dir is not None and self._p3_last_direction is not None:
            if _new_dir != self._p3_last_direction:
                if self._p3_direction_hold < P3_DEADBAND_CYCLES:
                    self._p3_direction_hold += 1
                    self.last_action = "HOLD"
                    return "HOLD"
                self._p3_direction_hold = 0

        self._p3_last_direction = _new_dir

        if th_n > target_t:
            self.last_action = "COAST"
            return "COAST"
        if th_n < target_t and not br_act:
            self.last_action = "ACCELERATE"
            return "ACCELERATE"
        self.last_action = "HOLD"
        return "HOLD"
