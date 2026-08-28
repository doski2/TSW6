#!/usr/bin/env python3
"""
speed_decider.py — Lógica de decisión de velocidad (P1 + FSM).

Solo frenado automático: el conductor acelera manualmente.
P1 usa frenado v2 (``tsw6/braking/v2``) para límites, estación y señal.

SpeedDecider recibe un TrainState y devuelve una acción de control:
  COAST | BRAKE | BRAKE_FAST | EMERGENCY | HOLD | PAUSED

Separación de responsabilidades:
  - SpeedDecider: SOLO decide qué hacer, sin saber cómo ejecutarlo
  - HandleController: SOLO ejecuta, sin saber por qué
  - SafetyWatchdog: override de emergencia (exceso persistente), sin P2

Estado interno permitido:
  - TrainPhysics (acelerómetro, learner)
  - StationFSM (paradas comerciales: puertas Lua / DMI)
  - BrakeCoordinatorV2 (límite / estación / señal + emergencias P1)

No hay seguimiento de notch interno. Toda la posición del handle se lee
de state.handle_notch (telemetría como fuente de verdad).
"""

import logging
from typing import Optional

from tsw6.braking.v2.policy import should_merge_limit_and_station_plans
from tsw6.braking.v2.coordinator import BrakeCoordinatorV2
from tsw6.telemetry.driver_aid_parser import station_base_name
from tsw6.autopilot.control_actions import (
    BRAKE, BRAKE_FAST, COAST, HOLD, PAUSED, RELEASE,
)
from tsw6.braking.v2.command import LIMIT_OVER_ACTIVE_MPH, release_brake_command
from tsw6.governor.governor_physics import TrainPhysics
from tsw6.governor.governor_station import StationFSM
from tsw6.autopilot.train_state import TrainState

_log = logging.getLogger("tsw.governor")


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
        self._braking   = BrakeCoordinatorV2()

        self.target_mph: float = target_mph
        self.paused:     bool  = False

        # Estado público para logging / dashboard
        self.effective_limit: float = 0.0
        self.last_action:     str   = HOLD

        # Caché del último TrainState visto (para propiedades de dashboard)
        self._last_state: Optional[TrainState] = None

        # P1 v2 — transición activo/inactivo para log de reset
        self._p1_was_active: bool = False
        self._schedule_slack_enabled: bool = False

    def set_schedule_slack_enabled(self, enabled: bool) -> None:
        self._schedule_slack_enabled = enabled
        self._braking.set_schedule_slack_enabled(enabled)

    # ── Physics API (llamar antes de decide() cada ciclo) ─────────────────

    def update_physics(self, speed_mph: float,
                       api_accel: Optional[float],
                       gradient_pct: float = 0.0) -> None:
        """Actualiza el acelerómetro y el learner con los datos del ciclo."""
        self._physics.record_speed(speed_mph)
        if api_accel is not None:
            self._physics._api_accel = api_accel

    def feed_learner(self, speed_mph: float, handle_notch: int,
                     gradient_pct: float, accel_ms2: Optional[float],
                     brake_cyl_bar: Optional[float] = None) -> None:
        """Alimenta el aprendiz online. Llamar una vez por ciclo.

        El learner usa la escala del handle combinado 0-8 (0=freno máx,
        4=neutro, 8=tracción máx), así que se pasa handle_notch tal cual.
        (Antes se restaba 4 y se registraban muescas erróneas.)"""
        self._physics.feed_learner(
            speed_mph, handle_notch, gradient_pct, accel_ms2,
            brake_cyl_bar=brake_cyl_bar,
        )

    def set_rain_intensity(self, intensity: float) -> None:
        self._physics.set_rain_intensity(intensity)

    def set_vehicle_profile(self, vehicle: str) -> None:
        """Carga el perfil de calibración del tren detectado (perfiles por tren)."""
        self._physics.set_vehicle_profile(vehicle)

    def adopt_vehicle_profile(self, vehicle: str) -> None:
        """Adopta el perfil del tren detectado a mitad de sesión conservando
        lo aprendido en lo que va de sesión (lo fusiona con el perfil en disco)."""
        self._physics.adopt_vehicle_profile(vehicle)

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

    def scheduled_next_stop(
        self, stations: Optional[list],
    ) -> Optional[dict]:
        """Próxima parada comercial respetando paradas ya servidas."""
        return self._fsm.select_next_stop(stations)

    def served_station_bases(self) -> set[str]:
        """Nombres base de paradas que no deben mostrarse como próxima."""
        return self._fsm._stop_exclude_bases()

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

    @property
    def brake_command(self):
        """Último ``BrakeCommand`` IPC del plan P1 (None si no hay plan activo)."""
        return self._braking.last_brake_command

    def brake_command_for(self, action: str, state: TrainState):
        """Comando IPC del plan P1 (watchdog sin plan usa teclado en HandleController)."""
        del action, state
        return self._braking.last_brake_command

    @property
    def p1_debug(self) -> str:
        return self._braking.last_debug

    @property
    def p1_active(self) -> bool:
        state = self._last_state
        if state is None:
            return False
        stations = list(state.stations) if state.stations else None
        return self._p1_should_run(state, state.speed_mph, stations)

    @property
    def p1_investigate_suffix(self) -> str:
        if hasattr(self._braking, "investigate_suffix"):
            return self._braking.investigate_suffix()
        return ""

    @property
    def p1_unified_stop(self) -> bool:
        if hasattr(self._braking, "unified_stop_latched"):
            return bool(self._braking.unified_stop_latched)
        return False

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

    def _p1_station_target(self, state: TrainState) -> Optional[str]:
        """Andén de la FSM en APPROACHING; no el next_stop ya saltado (C.2)."""
        fsm_state = self._fsm.state or state.station_state
        if fsm_state == "APPROACHING":
            return self._fsm.name or state.station_name or state.next_stop_name
        return state.next_stop_name or self._fsm.name or state.station_name

    def _p1_station_distance(
        self,
        state: TrainState,
        stations: Optional[list],
    ) -> Optional[float]:
        target = self._p1_station_target(state)
        if stations and target:
            tbase = station_base_name(target)
            for st in stations:
                name = st.get("name")
                if not name:
                    continue
                if name == target or station_base_name(str(name)) == tbase:
                    d = st.get("distance_m")
                    if d is not None:
                        return float(d)
        if (
            target
            and state.next_stop_name
            and station_base_name(target) != station_base_name(state.next_stop_name)
        ):
            return None
        return state.next_stop_distance_m

    def _p1_should_run(
        self,
        state: TrainState,
        speed_mph: float,
        stations: Optional[list],
    ) -> bool:
        """
        P1 activo salvo APPROACHING/DEPARTING lento — salvo cartel agrupado
        con la estación, o palanca aún en freno (C.2: no reset @10 mph con B1).
        """
        fsm_state = self._fsm.state or state.station_state
        if fsm_state == "STOPPED":
            return False
        if fsm_state not in ("APPROACHING", "DEPARTING"):
            return True
        if state.brake_active:
            return True
        if (
            fsm_state == "APPROACHING"
            and self._p1_was_active
            and speed_mph <= 12.0
        ):
            return True
        if speed_mph > 10.0:
            return True
        if fsm_state != "APPROACHING":
            return False

        dist_lim = state.distance_next_m
        lim = state.next_limit_mph
        dist_stn = self._p1_station_distance(state, stations)
        if (
            dist_lim is not None
            and dist_stn is not None
            and lim is not None
            and should_merge_limit_and_station_plans(dist_lim, dist_stn)
            and dist_lim > 50
            and speed_mph > lim + LIMIT_OVER_ACTIVE_MPH
        ):
            return True
        return False

    def _mark_p1_off_debug(self) -> None:
        st = self._fsm.state
        if st is None and self._last_state is not None:
            st = self._last_state.station_state
        self._braking.last_debug = f"p1off:{st}" if st else "p1off"

    # ── Decisión principal ────────────────────────────────────────────────

    def decide(self, state: TrainState) -> str:
        """
        Decide la acción de control para el ciclo actual.

        Capas de prioridad (mayor a menor):
          FSM estación → marcador DMI → P1 (v2) → HOLD

        Sin crucero reactivo (P2): la contención en bajada va en limit_brake (P1).

        Garantía: siempre devuelve una de:
          COAST | BRAKE | BRAKE_FAST | EMERGENCY | HOLD | PAUSED
        """
        self._last_state = state

        if state.paused:
            self.last_action = PAUSED
            return PAUSED

        speed   = state.speed_mph
        limit   = state.limit_mph
        grad    = state.gradient_pct
        a       = state.acceleration_ms2  # puede ser None

        # Atajos locales (reducen ruido visual en el código)
        th_n    = state.throttle_notch     # 0-4
        th_act  = state.throttle_active

        # ── FSM de paradas en estación ────────────────────────────────────
        stations_list = list(state.stations) if state.stations else None
        speed_lims_list = list(state.speed_limits_ahead) if state.speed_limits_ahead else None

        action_override, eff_limit_override = self._fsm.update_state_transitions(
            speed_mph       = speed,
            limit_mph       = limit,
            stations        = stations_list,
            doors_open      = state.doors_open,
            doors_dmi       = state.doors_dmi,
            doors_telem     = state.doors_telem,
            braking_dist_fn = self._physics.braking_distance,
            eff_max_decel   = self._physics.eff_max_decel,
            eff_k_stop      = self._physics.eff_k_stop,
            next_limit_mph  = state.next_limit_mph,
            distance_next_m = state.distance_next_m,
        )

        if action_override is not None:
            if self._fsm.state == "DEPARTING" and state.brake_active:
                rel = release_brake_command(at_target=True)
                self._braking.reset()
                self._braking.last_brake_command = rel
                self._mark_p1_off_debug()
                self._p1_was_active = False
                self.effective_limit = 0.0
                self.last_action = RELEASE
                return RELEASE
            if self._fsm.state == "STOPPED":
                self._braking.reset()
                self._mark_p1_off_debug()
                self._p1_was_active = False
            self.effective_limit = eff_limit_override or 0.0
            self.last_action = action_override
            return action_override

        # Salida de andén: liberar freno residual
        if self._fsm.state == "DEPARTING" and speed < 25.0 and state.brake_active:
            self.effective_limit = limit
            self.last_action = COAST
            return COAST

        # Límite efectivo de crucero
        effective_limit = (min(limit, state.target_mph)
                           if state.target_mph > 0 else limit)

        if (
            state.station_state == "APPROACHING"
            and eff_limit_override is not None
            and eff_limit_override > 0
        ):
            effective_limit = min(effective_limit, eff_limit_override)

        # ── Marcador de freno advisory (DMI) ─────────────────────────────
        bm = state.brake_marker_m
        if bm is not None and speed > limit - 1.0:
            bm_bd = self._physics.braking_distance(speed, limit, gradient_pct=grad)
            if bm <= bm_bd:
                effective_limit = min(effective_limit, limit)
            if bm <= max(50.0, bm_bd * 0.25) and speed > limit + 1.0:
                _log.warning(
                    "Marcador freno BRAKE_FAST  spd=%.1f  lim=%.1f  "
                    "marker=%.0fm  bd=%.0fm",
                    speed, limit, bm, bm_bd)
                act = BRAKE_FAST
                self.effective_limit = effective_limit
                self.last_action = act
                return act
            if bm <= bm_bd * 0.6 and speed > limit:
                act = COAST if th_act else BRAKE
                self.effective_limit = effective_limit
                self.last_action = act
                return act

        # ── P1: Frenado anticipado al próximo límite ──────────────────────
        _p1_active = self._p1_should_run(
            state, speed, stations_list,
        )
        if not _p1_active:
            if self._p1_was_active and state.brake_active:
                _log.info(
                    "P1 reset → RELEASE fsm=%s spd=%.1f stop=%s",
                    self._fsm.state or state.station_state,
                    speed,
                    self._fsm.name or state.station_name or state.next_stop_name or "—",
                )
                rel = release_brake_command(at_target=True)
                self._braking.reset()
                self._braking.last_brake_command = rel
                self._mark_p1_off_debug()
                self._p1_was_active = False
                self.effective_limit = effective_limit
                self.last_action = RELEASE
                return RELEASE
            if self._p1_was_active:
                _log.info(
                    "P1 reset fsm=%s spd=%.1f stop=%s",
                    self._fsm.state or state.station_state,
                    speed,
                    self._fsm.name or state.station_name or state.next_stop_name or "—",
                )
            self._braking.reset()
            self._mark_p1_off_debug()
        else:
            _station_dist = self._p1_station_distance(state, stations_list)
            p1_action, effective_limit = self._braking.evaluate(
                speed_mph          = speed,
                next_limit_mph     = state.next_limit_mph,
                distance_next_m    = state.distance_next_m,
                effective_limit    = effective_limit,
                gradient_pct       = grad,
                acceleration_ms2   = a,
                throttle_notch     = th_n,
                speed_limits_ahead = speed_lims_list,
                base_decel_ms2     = self._physics.eff_max_decel,
                predict_decel      = self._physics.predict_brake_decel_ms2,
                handle_notch       = state.handle_notch,
                station_distance_m = _station_dist,
                station_name     = self._p1_station_target(state),
                station_eta      = state.next_stop_arrival,
                brake_transition_s = self._physics.brake_transition_s,
                brake_fill_s       = self._physics.brake_fill_s,
            )
            if p1_action is not None:
                self.effective_limit = effective_limit
                self.last_action = p1_action
                self._p1_was_active = True
                return p1_action

        self._p1_was_active = _p1_active
        self.effective_limit = effective_limit
        self.last_action = HOLD
        return HOLD
