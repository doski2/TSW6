"""FSM mínima andén — suprime P1 estación en STOPPED/DEPARTING (paso 7 reducido)."""

from __future__ import annotations

import time
from typing import Optional

STATION_STOPPED_MPH = 1.5
DEPARTING_CLEAR_MPH = 25.0
DEPARTING_MAX_S = 90.0
PLATFORM_AT_STOP_M = 55.0
DOORS_OPEN_MAX_SPEED_MPH = 8.0


def doors_effective(
    *,
    doors_open: Optional[bool] = None,
    doors_telem: Optional[bool] = None,
    doors_dmi: Optional[bool] = None,
) -> Optional[bool]:
    """Abierto si telem o DMI lo dicen; si no, ``doors_open``. ``None`` = sin dato."""
    if doors_telem is True or doors_dmi is True:
        return True
    if doors_telem is False and doors_dmi is False:
        return False
    if doors_open is True:
        return True
    if doors_open is False:
        return False
    if doors_telem is False or doors_dmi is False:
        return False
    return None


def _left_platform(
    *,
    speed_mph: float,
    station_dist_m: Optional[float],
) -> bool:
    """Tren fuera del andén sin ciclo puertas (sesión 210853Z)."""
    if speed_mph >= DEPARTING_CLEAR_MPH:
        return True
    if station_dist_m is None:
        return speed_mph > DOORS_OPEN_MAX_SPEED_MPH
    if station_dist_m > PLATFORM_AT_STOP_M:
        return True
    # Planning: stn≈0 al pasar el marker con el tren en marcha.
    if station_dist_m <= 1.0 and speed_mph > STATION_STOPPED_MPH:
        return True
    return False


class StationDwellGate:
    """
    Estados: ``None`` | ``STOPPED`` | ``DEPARTING``.

    Sin lista HTTP de paradas — solo distancia planning + probe puertas.
    Salida de STOPPED: ciclo puertas o haber dejado el andén (distancia/velocidad).
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
        open_now = doors_effective(
            doors_open=doors_open,
            doors_telem=doors_telem,
            doors_dmi=doors_dmi,
        ) is True

        if self.state == "DEPARTING":
            dwell = time.monotonic() - self._departing_at if self._departing_at else 0.0
            if speed_mph >= DEPARTING_CLEAR_MPH or dwell >= DEPARTING_MAX_S:
                self.state = None
                self._doors_opened = False
                self._departing_at = 0.0
            return

        if self.state == "STOPPED":
            if _left_platform(speed_mph=speed_mph, station_dist_m=station_dist_m):
                if speed_mph >= DEPARTING_CLEAR_MPH:
                    self.state = None
                    self._doors_opened = False
                    self._departing_at = 0.0
                else:
                    self._enter_departing()
                return
            if open_now:
                self._doors_opened = True
                return
            if self._doors_opened and not open_now:
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
