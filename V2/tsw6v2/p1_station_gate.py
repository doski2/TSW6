"""FSM mínima andén — suprime P1 estación en STOPPED/DEPARTING (paso 7 reducido)."""

from __future__ import annotations

import time
from typing import Optional

STATION_STOPPED_MPH = 1.5
DEPARTING_CLEAR_MPH = 25.0
DEPARTING_MAX_S = 90.0
PLATFORM_AT_STOP_M = 40.0
DOORS_OPEN_MAX_SPEED_MPH = 8.0


def _doors_effective(
    *,
    doors_open: Optional[bool],
    doors_telem: Optional[bool],
    doors_dmi: Optional[bool],
) -> bool:
    if doors_telem is True or doors_dmi is True:
        return True
    return doors_open is True


class StationDwellGate:
    """
    Estados: ``None`` | ``STOPPED`` | ``DEPARTING``.

    Sin lista HTTP de paradas — solo distancia planning + probe puertas/velocidad.
    """

    def __init__(self) -> None:
        self.state: Optional[str] = None
        self._doors_opened = False
        self._departing_at = 0.0

    def suppress_station_brake(self) -> bool:
        return self.state in ("STOPPED", "DEPARTING")

    def update(
        self,
        *,
        speed_mph: float,
        station_dist_m: Optional[float],
        doors_open: Optional[bool] = None,
        doors_telem: Optional[bool] = None,
        doors_dmi: Optional[bool] = None,
    ) -> None:
        open_now = _doors_effective(
            doors_open=doors_open,
            doors_telem=doors_telem,
            doors_dmi=doors_dmi,
        )

        if self.state == "DEPARTING":
            dwell = time.monotonic() - self._departing_at if self._departing_at else 0.0
            if speed_mph >= DEPARTING_CLEAR_MPH or dwell >= DEPARTING_MAX_S:
                self.state = None
                self._doors_opened = False
                self._departing_at = 0.0
            return

        if self.state == "STOPPED":
            if open_now:
                self._doors_opened = True
                return
            if self._doors_opened and not open_now:
                self._enter_departing()
                return
            if speed_mph > DEPARTING_CLEAR_MPH * 0.35:
                self._enter_departing()
            return

        at_platform = (
            station_dist_m is not None
            and station_dist_m <= PLATFORM_AT_STOP_M
            and speed_mph <= STATION_STOPPED_MPH
        )
        doors_at_stop = open_now and speed_mph <= DOORS_OPEN_MAX_SPEED_MPH
        if at_platform or doors_at_stop:
            self.state = "STOPPED"
            self._doors_opened = open_now

    def _enter_departing(self) -> None:
        self.state = "DEPARTING"
        self._departing_at = time.monotonic()
        self._doors_opened = False
