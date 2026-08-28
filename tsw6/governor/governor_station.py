#!/usr/bin/env python3
"""
governor_station.py — FSM comercial de paradas (APPROACHING / STOPPED / DEPARTING).

No es el perfil de freno P1 (eso es ``station_plan.py``).

Puertas: probe Lua ``doors_telem`` / DMI ``doors_dmi``.
  abrir → STOPPED; cerrar tras abrir → DEPARTING.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Optional, Tuple

from tsw6.braking.v2.physics import (
    MPH_TO_MS,
    apply_zone_margin_m,
    brake_reaction_margin_m,
)
from tsw6.braking.v2.policy import should_merge_limit_and_station_plans
from tsw6.governor.governor_constants import STATION_STOPPED_MPH
from tsw6.telemetry.driver_aid_parser import (
    resolve_station_door_state,
    select_next_scheduled_stop,
    station_base_name,
)

_log = logging.getLogger("tsw.station")


class StationFSM:
    """Máquina de estados: None | APPROACHING | STOPPED | DEPARTING."""

    def __init__(self):
        self.state: Optional[str] = None
        self.name: Optional[str] = None
        self._creep_to_station: bool = False

        self.target_stop_min_m: Optional[float] = None
        self._locked_stop_name: Optional[str] = None

        self._doors_opened: bool = False
        self._stopped_at: float = 0.0
        self._we_stopped: bool = False

        self._min_stop_dist: Optional[float] = None

        self._last_departed_name: Optional[str] = None
        self._last_departed_at: float = 0.0
        self._DEPARTURE_COOLDOWN_S = 60.0

        self._served_bases: set[str] = set()

    def _stop_exclude_bases(self) -> set[str]:
        ex = set(self._served_bases)
        if self.state in ("STOPPED", "DEPARTING") and self.name:
            ex.add(station_base_name(self.name))
        if self._last_departed_name:
            ex.add(station_base_name(self._last_departed_name))
        return ex

    def select_next_stop(self, stations: Optional[list]) -> Optional[dict]:
        if self.target_stop_min_m is not None and self.target_stop_min_m <= 0:
            return None
        if self.target_stop_min_m is not None:
            if self._locked_stop_name is None:
                valid = [s for s in (stations or []) if s["distance_m"] > 200]
                if valid:
                    best = min(
                        valid,
                        key=lambda s: abs(s["distance_m"] - self.target_stop_min_m),
                    )
                    self._locked_stop_name = best["name"]
                    _log.info(
                        "Parada bloqueada: '%s'  dist=%.1fkm  (objetivo: %.1fkm)",
                        self._locked_stop_name,
                        best["distance_m"] / 1000.0,
                        self.target_stop_min_m / 1000.0,
                    )
            if self._locked_stop_name is not None:
                return next(
                    (s for s in (stations or []) if s["name"] == self._locked_stop_name),
                    None,
                )
            return None
        return select_next_scheduled_stop(
            stations, exclude_bases=self._stop_exclude_bases())

    def update_state_transitions(
        self,
        speed_mph: float,
        limit_mph: float,
        stations: Optional[list],
        doors_open: bool,
        doors_dmi: Optional[bool],
        braking_dist_fn,
        eff_max_decel: float,
        eff_k_stop: float,
        doors_telem: Optional[bool] = None,
        next_limit_mph: Optional[float] = None,
        distance_next_m: Optional[float] = None,
    ) -> Tuple[Optional[str], float]:
        next_stop = self.select_next_stop(stations)

        if self.state == "DEPARTING":
            _dep_base = station_base_name(self.name or "")
            _nxt_base = (
                station_base_name(next_stop["name"]) if next_stop else ""
            )
            _cleared = (
                next_stop is None
                or float(next_stop.get("distance_m") or 0) > 200
                or (_dep_base and _nxt_base and _nxt_base != _dep_base)
            )
            if _cleared:
                if _dep_base:
                    self._served_bases.add(_dep_base)
                _log.info("FSM: DEPARTING → None")
                self._last_departed_name = self.name
                self._last_departed_at = time.time()
                self.state = None
                self.name = None
                self._min_stop_dist = None
                if (
                    self.target_stop_min_m is not None
                    and self._locked_stop_name == self._last_departed_name
                ):
                    self._locked_stop_name = None
                    self.target_stop_min_m = None
                    _log.info("Parada manual liberada – modo sin paradas activo")

        if self.state is None and next_stop is not None:
            brake_needed = braking_dist_fn(speed_mph, 0.0)
            speed_ms = speed_mph * MPH_TO_MS
            react_m = brake_reaction_margin_m(speed_ms)
            approach_pad_m = react_m + apply_zone_margin_m(
                speed_ms, brake_needed + react_m)
            if next_stop["distance_m"] <= brake_needed + approach_pad_m:
                _dep_base = (self._last_departed_name or "").split(",")[0].strip().lower()
                _stn_base = next_stop["name"].split(",")[0].strip().lower()
                _in_cooldown = (
                    _dep_base and _stn_base == _dep_base
                    and time.time() - self._last_departed_at < self._DEPARTURE_COOLDOWN_S
                )
                if _in_cooldown:
                    _log.debug(
                        "APPROACHING bloqueado (cooldown %.0fs)  '%s'",
                        self._DEPARTURE_COOLDOWN_S - (time.time() - self._last_departed_at),
                        next_stop["name"],
                    )
                else:
                    _plat = next_stop.get("platform_length_m")
                    _sw = max(50.0, _plat / 2.0) if _plat else 50.0
                    if speed_mph <= STATION_STOPPED_MPH and next_stop["distance_m"] < _sw:
                        _log.info(
                            "FSM: None → STOPPED (en andén)  '%s'  dist=%.0fm  ventana=%.0fm  spd=%.1f",
                            next_stop["name"], next_stop["distance_m"], _sw, speed_mph,
                        )
                        self.state = "STOPPED"
                        self.name = next_stop["name"]
                        self._stopped_at = time.time()
                        self._doors_opened = (doors_telem is True) or (doors_dmi is True)
                        self._we_stopped = False
                        self._min_stop_dist = None
                        return "HOLD", 0.0

                    _log.info(
                        "FSM: None → APPROACHING  '%s'  dist=%.0fm  spd=%.1f",
                        next_stop["name"], next_stop["distance_m"], speed_mph,
                    )
                    self.state = "APPROACHING"
                    self.name = next_stop["name"]
                    self._min_stop_dist = next_stop["distance_m"]
                    self._we_stopped = (speed_mph > STATION_STOPPED_MPH)

        if self.state == "STOPPED":
            return self._handle_stopped(
                speed_mph, doors_open, doors_dmi,
                doors_telem=doors_telem, next_stop=next_stop)

        if self.state == "APPROACHING":
            return self._handle_approaching(
                speed_mph, limit_mph, next_stop, doors_open, doors_dmi,
                braking_dist_fn, eff_max_decel, eff_k_stop,
                doors_telem=doors_telem,
                next_limit_mph=next_limit_mph,
                distance_next_m=distance_next_m,
                stations=stations,
            )

        return None, 0.0

    def _mark_current_stop_served(self) -> None:
        if self.name:
            base = station_base_name(self.name)
            if base:
                self._served_bases.add(base)

    def _handle_door_service_at_stop(
        self,
        speed_mph: float,
        *,
        doors_open: bool,
        doors_dmi: Optional[bool],
        doors_telem: Optional[bool] = None,
    ) -> bool:
        """Lua/DMI: abrir → STOPPED; cerrar tras abrir → DEPARTING."""
        if speed_mph > STATION_STOPPED_MPH or not self.name:
            return False
        effective, src = resolve_station_door_state(
            doors_telem=doors_telem,
            doors_dmi=doors_dmi,
            doors_open=doors_open,
        )
        if effective:
            if not self._doors_opened:
                _log.info("FSM: puertas abiertas (src=%s)  '%s'", src, self.name)
            self._doors_opened = True
            if self.state == "APPROACHING":
                _log.info("FSM: APPROACHING → STOPPED (puertas)  '%s'", self.name)
                self.state = "STOPPED"
                self._stopped_at = time.time()
                self._we_stopped = True
            return False
        if self._doors_opened and not effective:
            self._mark_current_stop_served()
            _log.info(
                "FSM: %s → DEPARTING (puertas cerradas, servida, src=%s)  '%s'",
                self.state, src, self.name,
            )
            self.state = "DEPARTING"
            self._doors_opened = False
            self._min_stop_dist = None
            return True
        return False

    def _handle_stopped(
        self,
        speed_mph: float,
        doors_open: bool,
        doors_dmi: Optional[bool],
        *,
        doors_telem: Optional[bool] = None,
        next_stop: Optional[dict] = None,
    ) -> Tuple[Optional[str], float]:
        del next_stop
        if self._handle_door_service_at_stop(
            speed_mph,
            doors_open=doors_open,
            doors_dmi=doors_dmi,
            doors_telem=doors_telem,
        ):
            return "HOLD", 0.0
        if (
            not self._doors_opened
            and speed_mph > 5.0
            and (time.time() - self._stopped_at) >= 3.0
        ):
            self._mark_current_stop_served()
            _log.info(
                "FSM: STOPPED → DEPARTING (salida spd=%.1f sin ciclo puertas)  '%s'",
                speed_mph, self.name or "?",
            )
            self.state = "DEPARTING"
            self._doors_opened = False
            return "HOLD", 0.0
        return "HOLD", 0.0

    def _approaching_api_dist_m(
        self,
        next_stop: Optional[dict],
        stations: Optional[list] = None,
    ) -> float:
        if self.name:
            tbase = station_base_name(self.name)
            for st in stations or []:
                name = st.get("name")
                if name and station_base_name(str(name)) == tbase:
                    return float(st.get("distance_m") or 0.0)
            if next_stop:
                nbase = station_base_name(str(next_stop.get("name") or ""))
                if nbase != tbase:
                    return 0.0
        if next_stop:
            return float(next_stop.get("distance_m") or 0.0)
        return 0.0

    def _handle_approaching(
        self,
        speed_mph: float,
        limit_mph: float,
        next_stop: Optional[dict],
        doors_open: bool,
        doors_dmi: Optional[bool],
        braking_dist_fn,
        eff_max_decel: float,
        eff_k_stop: float,
        *,
        doors_telem: Optional[bool] = None,
        next_limit_mph: Optional[float] = None,
        distance_next_m: Optional[float] = None,
        stations: Optional[list] = None,
    ) -> Tuple[Optional[str], float]:
        del braking_dist_fn, eff_max_decel
        api_dist = self._approaching_api_dist_m(next_stop, stations)
        next_is_other = False
        if self.name and next_stop:
            next_is_other = (
                station_base_name(str(next_stop.get("name") or ""))
                != station_base_name(self.name)
            )

        if self._handle_door_service_at_stop(
            speed_mph,
            doors_open=doors_open,
            doors_dmi=doors_dmi,
            doors_telem=doors_telem,
        ):
            return "HOLD", 0.0

        raw_dist = api_dist
        if self._min_stop_dist is None or raw_dist < self._min_stop_dist:
            self._min_stop_dist = raw_dist
        stop_dist_m = self._min_stop_dist
        plat_len = next_stop.get("platform_length_m") if next_stop else None
        stop_window = max(50.0, plat_len / 2.0) if plat_len else 50.0

        at_platform = (
            speed_mph <= STATION_STOPPED_MPH
            and (
                stop_dist_m < stop_window
                or next_is_other
                or (self._we_stopped and stop_dist_m < 150.0)
                or (self._we_stopped and self._creep_to_station)
            )
        )
        if at_platform:
            _log.info(
                "FSM: APPROACHING → STOPPED  '%s'  stop_dist=%.1fm",
                self.name or "?", stop_dist_m,
            )
            self.state = "STOPPED"
            self._creep_to_station = False
            self._doors_opened = (doors_telem is True) or (doors_dmi is True)
            self._stopped_at = time.time()
            self._min_stop_dist = None
            return "HOLD", 0.0

        if stop_dist_m < stop_window:
            self._creep_to_station = False
        elif speed_mph <= STATION_STOPPED_MPH:
            self._creep_to_station = True

        if stop_dist_m < stop_window:
            return None, 0.0

        _stn_dist = api_dist
        if (
            distance_next_m is not None
            and next_limit_mph is not None
            and _stn_dist > 0
            and should_merge_limit_and_station_plans(distance_next_m, _stn_dist)
            and distance_next_m > 80
            and speed_mph > next_limit_mph + 1.0
        ):
            return None, 0.0

        eff_lim = min(limit_mph or 30.0, eff_k_stop * math.sqrt(stop_dist_m))
        if self._creep_to_station:
            eff_lim = min(eff_lim, 10.0)
        return None, eff_lim
