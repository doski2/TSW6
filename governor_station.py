#!/usr/bin/env python3
"""
governor_station.py — Lógica de la máquina de estados de paradas en estación (StationFSM).

Gestiona los estados APPROACHING, STOPPED, DEPARTING y la lógica de control de puertas,
dwell (embarque) y calibración de distancia OCR vs API.
"""

import logging
import time
import math
from typing import Optional, Tuple

from governor_constants import (
    STATION_APPROACH_M, STATION_STOPPED_MPH, STATION_DWELL_TIMEOUT_S,
)

_log = logging.getLogger("tsw.station")


class StationFSM:
    """Máquina de estados para paradas en estación (None | APPROACHING | STOPPED | DEPARTING)."""

    def __init__(self):
        self.state: Optional[str] = None       # None|APPROACHING|STOPPED|DEPARTING
        self.name:  Optional[str] = None
        self._creep_to_station: bool = False   # avanzar si el tren paró antes del andén

        # Parada manual
        self.target_stop_min_m: Optional[float] = None
        self._locked_stop_name: Optional[str]  = None

        # Seguimiento de puertas y dwell
        self._doors_opened: bool = False
        self._stopped_at: float = 0.0
        self._we_stopped: bool = False

        # Filtro de distancia mínima para ignorar el jitter de la API
        self._min_stop_dist: Optional[float] = None

        # Desfase API ↔ OCR
        self._ocr_offset: Optional[float] = None
        self._ocr_used: bool = False

        # Cooldown post-salida
        self._last_departed_name: Optional[str] = None
        self._last_departed_at:   float         = 0.0
        self._DEPARTURE_COOLDOWN_S              = 60.0

    def select_next_stop(self, stations: Optional[list]) -> Optional[dict]:
        """Selecciona la siguiente parada válida según modo manual o automático."""
        if self.target_stop_min_m is not None and self.target_stop_min_m <= 0:
            return None
        elif self.target_stop_min_m is not None:
            if self._locked_stop_name is None:
                # Excluir la estación actual (distance_m <= 200m)
                valid = [s for s in (stations or []) if s["distance_m"] > 200]
                if valid:
                    best = min(valid, key=lambda s: abs(s["distance_m"] - self.target_stop_min_m))
                    self._locked_stop_name = best["name"]
                    _log.info("Parada bloqueada: '%s'  dist=%.1fkm  (objetivo: %.1fkm)",
                              self._locked_stop_name, best["distance_m"] / 1000.0,
                              self.target_stop_min_m / 1000.0)
            if self._locked_stop_name is not None:
                return next((s for s in (stations or []) if s["name"] == self._locked_stop_name), None)
            return None
        else:
            return stations[0] if stations else None

    def update_state_transitions(self, speed_mph: float, limit_mph: float,
                                 stations: Optional[list],
                                 doors_open: bool, doors_dmi: Optional[bool],
                                 ocr_stop_dist_m: Optional[float],
                                 ocr_task: Optional[str],
                                 braking_dist_fn, eff_max_decel: float,
                                 eff_k_stop: float) -> Tuple[Optional[str], float]:
        """
        Ejecuta las transiciones de la FSM de estación basándose en telemetría.
        Devuelve una tupla (accion_override, effective_limit_override) si el estado
        de la estación requiere fijar o forzar el control (por ejemplo, en parada).
        """
        next_stop = self.select_next_stop(stations)

        # ── Transición DEPARTING → None ──────────────────────────────────────
        if self.state == "DEPARTING":
            if next_stop is None or next_stop["distance_m"] > 200:
                _log.info("FSM: DEPARTING → None")
                self._last_departed_name = self.name
                self._last_departed_at   = time.time()
                self.state  = None
                self.name   = None
                self._min_stop_dist = None
                self._ocr_offset    = None
                self._ocr_used      = False
                if self.target_stop_min_m is not None and self._locked_stop_name == self._last_departed_name:
                    self._locked_stop_name = None
                    self.target_stop_min_m = None
                    _log.info("Parada manual liberada – modo sin paradas activo")

        # ── Transición None → APPROACHING / STOPPED ──────────────────────────
        if self.state is None and next_stop is not None:
            brake_needed = braking_dist_fn(speed_mph, 0.0)
            if next_stop["distance_m"] <= brake_needed + STATION_APPROACH_M:
                _dep_base = (self._last_departed_name or "").split(",")[0].strip().lower()
                _stn_base = next_stop["name"].split(",")[0].strip().lower()
                _in_cooldown = (
                    _dep_base and _stn_base == _dep_base
                    and time.time() - self._last_departed_at < self._DEPARTURE_COOLDOWN_S
                )
                if _in_cooldown:
                    _log.debug("APPROACHING bloqueado (cooldown %.0fs)  '%s'",
                               self._DEPARTURE_COOLDOWN_S - (time.time() - self._last_departed_at),
                               next_stop["name"])
                else:
                    _plat = next_stop.get("platform_length_m")
                    _sw   = max(50.0, _plat / 2.0) if _plat else 50.0
                    if speed_mph <= STATION_STOPPED_MPH and next_stop["distance_m"] < _sw:
                        _log.info("FSM: None → STOPPED (en andén)  '%s'  dist=%.0fm  ventana=%.0fm  spd=%.1f",
                                  next_stop["name"], next_stop["distance_m"], _sw, speed_mph)
                        self.state          = "STOPPED"
                        self.name           = next_stop["name"]
                        self._stopped_at    = time.time()
                        self._doors_opened  = (doors_dmi is True)
                        self._we_stopped    = False
                        self._min_stop_dist = None
                        self._ocr_offset    = None
                        self._ocr_used      = False
                        return "HOLD", 0.0
                    
                    _log.info("FSM: None → APPROACHING  '%s'  dist=%.0fm  spd=%.1f",
                              next_stop["name"], next_stop["distance_m"], speed_mph)
                    self.state          = "APPROACHING"
                    self.name           = next_stop["name"]
                    self._min_stop_dist = next_stop["distance_m"]
                    self._ocr_offset    = None
                    self._ocr_used      = False
                    self._we_stopped    = (speed_mph > STATION_STOPPED_MPH)

        # ── Estado: STOPPED ──────────────────────────────────────────────────
        if self.state == "STOPPED":
            return self._handle_stopped(
                doors_open, doors_dmi, ocr_stop_dist_m, ocr_task)

        # ── Estado: APPROACHING ──────────────────────────────────────────────
        if self.state == "APPROACHING":
            return self._handle_approaching(
                speed_mph, limit_mph, next_stop, doors_dmi, ocr_stop_dist_m,
                braking_dist_fn, eff_max_decel, eff_k_stop)

        return None, 0.0

    # ── Handlers por estado ───────────────────────────────────────────────────

    def _handle_stopped(self, doors_open: bool, doors_dmi: Optional[bool],
                        ocr_stop_dist_m: Optional[float],
                        ocr_task: Optional[str]) -> Tuple[Optional[str], float]:
        """Gestiona el estado STOPPED: puertas, dwell y transición a DEPARTING."""
        _OCR_NEXT_STOP_M = 300.0
        if doors_dmi is True:
            effective_doors = True
            _ocr_door_src   = "dmi-open"
        elif doors_dmi is False:
            effective_doors = False
            _ocr_door_src   = "dmi-closed"
        elif ocr_task == "board":
            effective_doors = True
            _ocr_door_src   = "ocr_task=board"
        elif ocr_task == "stop":
            effective_doors = False
            _ocr_door_src   = "ocr_task=stop"
        elif ocr_stop_dist_m is not None and ocr_stop_dist_m > _OCR_NEXT_STOP_M:
            effective_doors = False
            _ocr_door_src   = f"ocr_dist={ocr_stop_dist_m:.0f}m>300m"
        elif ocr_stop_dist_m is None and ocr_task is None:
            effective_doors = True
            _ocr_door_src   = "ocr_sin_dist(embarcando)"
        else:
            effective_doors = doors_open
            _ocr_door_src   = "event"

        if effective_doors:
            if not self._doors_opened:
                _log.info("FSM: STOPPED puertas abiertas (src=%s)  (%s)",
                          _ocr_door_src, self.name or "?")
            self._doors_opened = True
            _dwell_s = 3.0 if not self._we_stopped else 15.0
            _dwell_label = " cold-start" if not self._we_stopped else " doors-stuck"
            if time.time() - self._stopped_at >= _dwell_s:
                _log.info("FSM: STOPPED → DEPARTING (timeout %.0fs%s, src=%s)  (%s)",
                          _dwell_s, _dwell_label, _ocr_door_src, self.name or "?")
                self.state = "DEPARTING"
                self._doors_opened = False
        elif self._doors_opened and not effective_doors:
            _log.info("FSM: STOPPED → DEPARTING (src=%s)  (%s)",
                      _ocr_door_src, self.name or "?")
            self.state  = "DEPARTING"
            self._doors_opened  = False
        else:
            if self._doors_opened:
                dwell_s = 15.0
                timeout_type = " doors-open-no-close"
            else:
                dwell_s = STATION_DWELL_TIMEOUT_S if self._we_stopped else 3.0
                timeout_type = "" if self._we_stopped else " cold-start"
            if time.time() - self._stopped_at >= dwell_s:
                _log.info("FSM: STOPPED → DEPARTING (timeout %.0fs%s)  (%s)",
                          dwell_s, timeout_type, self.name or "?")
                self.state = "DEPARTING"
                self._doors_opened = False
        return "HOLD", 0.0

    def _handle_approaching(self, speed_mph: float, limit_mph: float,
                            next_stop: Optional[dict], doors_dmi: Optional[bool],
                            ocr_stop_dist_m: Optional[float],
                            braking_dist_fn, eff_max_decel: float,
                            eff_k_stop: float) -> Tuple[Optional[str], float]:
        """Gestiona el estado APPROACHING: calibración OCR, perfil cinemático y transición a STOPPED."""
        api_dist = next_stop["distance_m"] if next_stop else 0.0

        # Calibración del offset OCR vs API
        if self._ocr_offset is None and ocr_stop_dist_m is not None:
            _v_ms       = speed_mph * 0.44704
            _phys_min   = (_v_ms * _v_ms) / (2.0 * eff_max_decel)
            _ocr_rel_ok = (ocr_stop_dist_m > api_dist * 0.10 and ocr_stop_dist_m < api_dist * 1.10)
            if ocr_stop_dist_m >= _phys_min and _ocr_rel_ok:
                self._ocr_offset = api_dist - ocr_stop_dist_m
                self._ocr_used   = True
                self._min_stop_dist = None
                _log.info("stop_dist  OCR CALIBRADO  API=%.1fm  OCR=%.1fm  offset=+%.1fm",
                          api_dist, ocr_stop_dist_m, self._ocr_offset)
            elif 0.0 < ocr_stop_dist_m < _phys_min:
                _log.debug("stop_dist  OCR rechazado (imposible frenar: min_fisico=%.0fm, ocr=%.0fm)",
                           _phys_min, ocr_stop_dist_m)
            elif ocr_stop_dist_m >= api_dist * 1.10:
                _log.debug("stop_dist  OCR rechazado (ocr=%.0fm > api*1.10=%.0fm)",
                           ocr_stop_dist_m, api_dist * 1.10)
            else:
                _log.debug("stop_dist  OCR rechazado (fuera de rango: api=%.0fm, ocr=%.0fm)",
                           api_dist, ocr_stop_dist_m)

        # Aplicar offset
        if self._ocr_offset is not None:
            raw_dist = max(0.0, api_dist - self._ocr_offset)
            _log.debug("stop_dist  API=%.1fm  offset=%.1fm → raw=%.1fm",
                       api_dist, self._ocr_offset, raw_dist)
        else:
            raw_dist = api_dist

        # Filtro monótono mínimo
        if self._min_stop_dist is None or raw_dist < self._min_stop_dist:
            self._min_stop_dist = raw_dist
        stop_dist_m = self._min_stop_dist
        plat_len    = next_stop.get("platform_length_m") if next_stop else None
        stop_window = max(50.0, plat_len / 2.0) if plat_len else 50.0

        # Transición APPROACHING → STOPPED
        if speed_mph <= STATION_STOPPED_MPH and stop_dist_m < stop_window:
            _log.info("FSM: APPROACHING → STOPPED  '%s'  stop_dist=%.1fm",
                      self.name or "?", stop_dist_m)
            self.state               = "STOPPED"
            self._creep_to_station   = False
            self._doors_opened       = False
            self._stopped_at         = time.time()
            self._min_stop_dist      = None
            self._ocr_offset         = None
            return "HOLD", 0.0

        # Creep: marcar si paró antes del andén (histéresis hasta entrar en andén)
        if stop_dist_m < stop_window:
            self._creep_to_station = False
        elif speed_mph <= STATION_STOPPED_MPH:
            self._creep_to_station = True

        # En andén parado: gestionar puertas directamente
        if speed_mph <= STATION_STOPPED_MPH and stop_dist_m < stop_window:
            if doors_dmi is True:
                self._doors_opened = True
            elif self._doors_opened and doors_dmi is False:
                _log.info("FSM: APPROACHING → DEPARTING (puertas cerradas)  '%s'", self.name or "?")
                self.state = "DEPARTING"
                self._doors_opened = False
                self._min_stop_dist = None
                self._ocr_offset    = None
            return "HOLD", 0.0

        # Perfil cinemático de velocidad límite para parar en el andén
        if stop_dist_m < stop_window:
            return None, 0.0
        else:
            eff_lim = min(limit_mph or 30.0, eff_k_stop * math.sqrt(stop_dist_m))
            if self._creep_to_station:
                eff_lim = min(eff_lim, 10.0)
            return None, eff_lim

        return None, 0.0
