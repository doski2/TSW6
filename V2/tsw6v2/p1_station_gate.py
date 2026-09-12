"""FSM mínima andén — suprime P1 estación en STOPPED/DEPARTING (paso 7 reducido).

Complementa ``should_suppress_station_braking_for_departure`` (``station_plan``):
esa función evita re-frenar en arranque heurístico; esta FSM cubre dwell,
puertas y passthrough cuando ``loop`` pone ``station_brake_enabled=False``.
"""

from __future__ import annotations

import time
from typing import Optional

STATION_STOPPED_MPH = 1.5
DEPARTING_CLEAR_MPH = 25.0
DEPARTING_MAX_S = 90.0
PLATFORM_AT_STOP_M = 55.0
DOORS_OPEN_MAX_SPEED_MPH = 8.0
# Rollo passthrough en andén: ≥10 mph sin puertas (9 mph neutro = aún parada).
PLATFORM_ROLL_THROUGH_MIN_MPH = 10.0
# Marker pasado con marcha (hueco 112457Z: paró a 1.48 mph con umbral >1.5).
MARKER_PASSED_MIN_MPH = 1.0


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
    if station_dist_m <= 1.0 and speed_mph >= MARKER_PASSED_MIN_MPH:
        return True
    return False


class StationDwellGate:
    """
    Estados: ``None`` | ``STOPPED`` | ``DEPARTING``.

    Sin lista HTTP de paradas — solo distancia planning + probe puertas.

    Passthrough sin puertas: ``_pass_through`` tras DEPARTING, o en vivo
    (tracción o ≥``PLATFORM_ROLL_THROUGH_MIN_MPH`` en stn≤55 m).
    """

    def __init__(self) -> None:
        self.state: Optional[str] = None
        self._doors_opened = False
        self._doors_ever_opened = False
        self._departing_at = 0.0
        self._pass_through = False

    def suppress_station_brake(
        self,
        *,
        station_dist_m: Optional[float] = None,
        throttle_notch: int = 4,
        speed_mph: float = 0.0,
    ) -> bool:
        """Suprime plan STATION: dwell, rollo sin puertas, o salida con tracción."""
        if self.state in ("STOPPED", "DEPARTING"):
            return True
        if self._pass_through:
            if station_dist_m is None or station_dist_m <= PLATFORM_AT_STOP_M:
                return True
            self._pass_through = False
        if (
            not self._doors_ever_opened
            and station_dist_m is not None
            and station_dist_m <= PLATFORM_AT_STOP_M
            and (
                throttle_notch > 4
                or speed_mph >= PLATFORM_ROLL_THROUGH_MIN_MPH
            )
        ):
            return True
        return False

    def _reset_idle(self) -> None:
        self.state = None
        self._doors_opened = False
        self._departing_at = 0.0

    def _clear_station_episode(self, station_dist_m: Optional[float]) -> None:
        if station_dist_m is not None and station_dist_m > PLATFORM_AT_STOP_M:
            self._pass_through = False
            self._doors_ever_opened = False

    def _handle_stopped(
        self,
        *,
        speed_mph: float,
        station_dist_m: Optional[float],
        open_now: bool,
        throttle_notch: int,
    ) -> None:
        """Salidas de STOPPED por prioridad.

        1. Geometría: marker (stn≤1 m), lejos del andén, o ≥25 mph.
        2. Puertas: ciclo abrir→cerrar.
        3. Passthrough: tracción (lever>4) sin haber abierto puertas.
        """
        if _left_platform(speed_mph=speed_mph, station_dist_m=station_dist_m):
            if speed_mph >= DEPARTING_CLEAR_MPH:
                self._reset_idle()
                self._clear_station_episode(station_dist_m)
            else:
                self._enter_departing()
            return
        if open_now:
            self._doors_opened = True
            return
        if self._doors_opened and not open_now:
            self._enter_departing()
            return
        if not self._doors_opened and throttle_notch > 4:
            self._enter_departing()

    def update(
        self,
        *,
        speed_mph: float,
        station_dist_m: Optional[float],
        doors_open: Optional[bool] = None,
        doors_telem: Optional[bool] = None,
        doors_dmi: Optional[bool] = None,
        throttle_notch: int = 4,
    ) -> None:
        open_now = doors_effective(
            doors_open=doors_open,
            doors_telem=doors_telem,
            doors_dmi=doors_dmi,
        ) is True
        if open_now:
            self._doors_ever_opened = True

        if self.state == "DEPARTING":
            dwell = time.monotonic() - self._departing_at if self._departing_at else 0.0
            if speed_mph >= DEPARTING_CLEAR_MPH or dwell >= DEPARTING_MAX_S:
                self._reset_idle()
        elif self.state == "STOPPED":
            self._handle_stopped(
                speed_mph=speed_mph,
                station_dist_m=station_dist_m,
                open_now=open_now,
                throttle_notch=throttle_notch,
            )
            return
        else:
            at_platform = (
                station_dist_m is not None
                and station_dist_m <= PLATFORM_AT_STOP_M
                and speed_mph <= STATION_STOPPED_MPH
            )
            doors_at_stop = open_now and speed_mph <= DOORS_OPEN_MAX_SPEED_MPH
            if doors_at_stop or (at_platform and self._doors_ever_opened):
                self.state = "STOPPED"
                self._doors_opened = open_now

        self._clear_station_episode(station_dist_m)

    def _enter_departing(self) -> None:
        self._pass_through = not self._doors_opened
        self.state = "DEPARTING"
        self._departing_at = time.monotonic()
        self._doors_opened = False
