"""FSM mínima andén — suprime P1 estación en STOPPED/DEPARTING (paso 7 reducido).

Complementa ``should_suppress_station_braking_for_departure`` (``station_plan``):
esa función evita re-frenar en arranque heurístico; esta FSM cubre dwell,
puertas y passthrough cuando ``loop`` pone ``station_brake_enabled=False``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from tsw6v2.constants import STATION_FINAL_APPROACH_RELEASE_BLOCK_M
from tsw6v2.command import (
    is_brake_applied,
    is_brake_released,
    throttle_notch_from_lever,
)
from tsw6v2.physics import PRESSURE_IDLE_MAX_BAR
from tsw6v2.limit_containment import try_downhill_coast_watch
from tsw6v2.limit_state import LimitBrakeState
from tsw6v2.station_plan import (
    DEFAULT_STATION_CFG,
    ORIGIN_DEPARTURE_MAX_SPEED_MPH,
    is_departure_creep_context,
    is_service_platform_departure,
    is_service_platform_parked_skip_release,
)
from tsw6v2.target import BrakeTargetResult

if TYPE_CHECKING:
    from tsw6v2.command import BrakeCommand

STATION_STOPPED_MPH = 1.5
DEPARTING_CLEAR_MPH = ORIGIN_DEPARTURE_MAX_SPEED_MPH
DEPARTING_MAX_S = 90.0
PLATFORM_AT_STOP_M = 55.0
DOORS_OPEN_MAX_SPEED_MPH = 8.0
# Rollo passthrough en andén: ≥10 mph sin puertas (9 mph neutro = aún parada).
PLATFORM_ROLL_THROUGH_MIN_MPH = 10.0
# Marker pasado con marcha (hueco 112457Z: paró a 1.48 mph con umbral >1.5).
MARKER_PASSED_MIN_MPH = 1.0


def _live_roll_through_without_doors(
    *,
    speed_mph: float,
    throttle_notch: int,
) -> bool:
    """
    Rollo en andén sin puertas: tracción, o neutro ~10–11 mph (no aproximación rápida).

    155851Z: neutro @13 mph tras parar en señal pegada al andén no es passthrough.
    """
    if throttle_notch < 4:
        return False
    if throttle_notch > 4:
        return True
    return (
        PLATFORM_ROLL_THROUGH_MIN_MPH
        <= speed_mph
        < DEFAULT_STATION_CFG.departure_speed_mph
    )


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


def station_departure_active(
    *,
    speed_mph: float,
    station_dist_m: Optional[float],
    combined_lever: int,
    station_fsm: Optional[str] = None,
) -> bool:
    """Arranque / salida andén: FSM DEPARTING u origen con tracción."""
    if station_fsm == "DEPARTING":
        return is_departure_creep_context(
            station_dist_m,
            speed_mph,
            station_fsm=station_fsm,
        )
    throttle = throttle_notch_from_lever(combined_lever)
    return is_service_platform_departure(
        speed_mph=speed_mph,
        station_distance_m=station_dist_m,
        throttle_notch=throttle,
        max_speed_mph=DEPARTING_CLEAR_MPH,
    )


def station_departure_suppresses_limit_brake(
    *,
    speed_mph: float,
    station_dist_m: Optional[float],
    combined_lever: int,
    station_fsm: Optional[str] = None,
) -> bool:
    """Creep salida: sin HOLD_DH cartel hasta ~11 mph (223013Z; coast watch aparte)."""
    if not station_departure_active(
        speed_mph=speed_mph,
        station_dist_m=station_dist_m,
        combined_lever=combined_lever,
        station_fsm=station_fsm,
    ):
        return False
    return speed_mph <= DEFAULT_STATION_CFG.departure_speed_mph


def departing_brake_needs_release(lever: int) -> bool:
    """B1–B3 en palanca (RELEASE IPC en salida)."""
    return is_brake_applied(lever)


def _service_platform_residual_pressure(
    brake_cyl_bar: Optional[float],
) -> bool:
    return (
        brake_cyl_bar is not None
        and float(brake_cyl_bar) > PRESSURE_IDLE_MAX_BAR
    )


def _service_platform_parked_bleed_context(
    *,
    speed_mph: float,
    station_dist_m: Optional[float],
    combined_lever: int,
    station_fsm: Optional[str] = None,
) -> bool:
    """Andén servicio (origen o mid-route) parado, sin creep de salida."""
    if station_departure_active(
        speed_mph=speed_mph,
        station_dist_m=station_dist_m,
        combined_lever=combined_lever,
        station_fsm=station_fsm,
    ):
        return False
    return is_service_platform_parked_skip_release(
        speed_mph=speed_mph,
        station_distance_m=station_dist_m,
    )


def _service_platform_skip_cartel_release(
    *,
    speed_mph: float,
    station_dist_m: Optional[float],
    combined_lever: int,
    platform_bleed_episode: bool = False,
    station_fsm: Optional[str] = None,
) -> bool:
    """
    Andén servicio parado: bloquear RELEASE cartel heredado.

    Neutro + presión alta → ``platform_bleed`` (no cartel). Episodio bleed activo
    + freno en palanca → RELEASE dedicado (195804Z: sin ping-pong B1/neutro).
    """
    if not _service_platform_parked_bleed_context(
        speed_mph=speed_mph,
        station_dist_m=station_dist_m,
        combined_lever=combined_lever,
        station_fsm=station_fsm,
    ):
        return False
    if is_brake_applied(combined_lever):
        return platform_bleed_episode
    return True


@dataclass
class PlatformBleedEpisode:
    """Un ciclo B1→neutro en andén; evita repetir APPLY mientras ventila (195804Z)."""

    active: bool = False

    def reset(self) -> None:
        self.active = False

    def note_bleed_apply(self) -> None:
        self.active = True

    def update(
        self,
        *,
        p1_reason: str,
        brake_cyl_bar: Optional[float],
        speed_mph: float,
        station_dist_m: Optional[float],
        combined_lever: int,
        station_fsm: Optional[str],
    ) -> None:
        if brake_cyl_bar is not None and float(brake_cyl_bar) <= PRESSURE_IDLE_MAX_BAR:
            self.reset()
            return
        if not _service_platform_parked_bleed_context(
            speed_mph=speed_mph,
            station_dist_m=station_dist_m,
            combined_lever=combined_lever,
            station_fsm=station_fsm,
        ):
            self.reset()
            return
        if p1_reason == "platform_bleed":
            self.note_bleed_apply()


def platform_parked_residual_bleed_needed(
    *,
    speed_mph: float,
    station_dist_m: Optional[float],
    combined_lever: int,
    brake_cyl_bar: Optional[float],
    station_fsm: Optional[str] = None,
    platform_bleed_episode: bool = False,
) -> bool:
    """
    Andén servicio, palanca en neutro/P y cilindros cargados (193606Z).

    TSW no ventila con mando en neutro: hay que meter B1 y luego RELEASE a neutro.
    """
    if not _service_platform_parked_bleed_context(
        speed_mph=speed_mph,
        station_dist_m=station_dist_m,
        combined_lever=combined_lever,
        station_fsm=station_fsm,
    ):
        return False
    if platform_bleed_episode:
        return False
    if not is_brake_released(combined_lever):
        return False
    return _service_platform_residual_pressure(brake_cyl_bar)


def platform_parked_bleed_release_needed(
    *,
    speed_mph: float,
    station_dist_m: Optional[float],
    combined_lever: int,
    station_fsm: Optional[str] = None,
    platform_bleed_episode: bool = False,
) -> bool:
    """Tras APPLY bleed: RELEASE a neutro sin cartel (195804Z)."""
    if not platform_bleed_episode:
        return False
    if not _service_platform_parked_bleed_context(
        speed_mph=speed_mph,
        station_dist_m=station_dist_m,
        combined_lever=combined_lever,
        station_fsm=station_fsm,
    ):
        return False
    return is_brake_applied(combined_lever)


def departure_limit_target_or_coast(
    limit_target: Optional[BrakeTargetResult],
    state: LimitBrakeState,
    *,
    speed_mph: float,
    station_dist_m: Optional[float],
    combined_lever: int,
    station_fsm: Optional[str],
    posted_limit_mph: Optional[float],
    gradient_pct: float,
    next_limit_mph: Optional[float],
    next_distance_m: Optional[float],
) -> Optional[BrakeTargetResult]:
    """
    Creep salida: HOLD_DH suprimido → coast watch hasta ``departure_speed_mph``.

    Evita ``no_plan`` entre techo zona (~10.2) y fin de creep (~11.2, 182951Z).
    """
    if limit_target is None:
        return None
    if not station_departure_suppresses_limit_brake(
        speed_mph=speed_mph,
        station_dist_m=station_dist_m,
        combined_lever=combined_lever,
        station_fsm=station_fsm,
    ):
        return limit_target
    if not limit_target.limit_brake_active:
        return limit_target
    if posted_limit_mph is None:
        return None
    return try_downhill_coast_watch(
        state,
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        gradient_pct=gradient_pct,
        next_limit_mph=next_limit_mph,
        next_distance_m=next_distance_m,
        coast_ceiling_mph=DEFAULT_STATION_CFG.departure_speed_mph,
    )


def should_skip_p1_release(
    *,
    speed_mph: float,
    station_dist_m: Optional[float],
    combined_lever: int,
    station_fsm: Optional[str] = None,
    brake_cyl_bar: Optional[float] = None,
    platform_bleed_episode: bool = False,
) -> bool:
    """
    En salida: un solo camino RELEASE (``_attempt_departing_brake_release``).

    Bloquea RELEASE heredado cartel/señal que pelea con tracción (182951Z).
    """
    if station_departure_active(
        speed_mph=speed_mph,
        station_dist_m=station_dist_m,
        combined_lever=combined_lever,
        station_fsm=station_fsm,
    ):
        return True
    if _service_platform_skip_cartel_release(
        speed_mph=speed_mph,
        station_dist_m=station_dist_m,
        combined_lever=combined_lever,
        platform_bleed_episode=platform_bleed_episode,
        station_fsm=station_fsm,
    ):
        return True
    # Marker pasado con marcha: permitir RELEASE cartel (passthrough / siguiente parada).
    if (
        station_dist_m is not None
        and station_dist_m <= 1.0
        and speed_mph >= MARKER_PASSED_MIN_MPH
    ):
        return False
    # Aproximación final: sin RELEASE cartel/señal heredado (213633Z @ 62 m).
    if (
        station_dist_m is not None
        and 0 < station_dist_m < STATION_FINAL_APPROACH_RELEASE_BLOCK_M
    ):
        return True
    return False


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
    (tracción o neutro ≥``PLATFORM_ROLL_THROUGH_MIN_MPH`` en stn≤55 m; no B1–B3).
    """

    def __init__(self) -> None:
        self.state: Optional[str] = None
        self._doors_opened = False
        self._doors_ever_opened = False
        self._departing_at = 0.0
        self._pass_through = False

    def _departing_suppresses_station_brake(
        self,
        *,
        station_dist_m: Optional[float],
        speed_mph: float,
    ) -> bool:
        """
        Creep salida sí; aproximación al próximo andén no.

        Sesión 211032Z: ``DEPARTING`` + stn≈559 m @ 20 mph bloqueaba P1 estación.
        """
        if self._pass_through and (
            station_dist_m is None or station_dist_m <= PLATFORM_AT_STOP_M
        ):
            return True
        return is_departure_creep_context(station_dist_m, speed_mph)

    def suppress_station_brake(
        self,
        *,
        station_dist_m: Optional[float] = None,
        throttle_notch: int = 4,
        speed_mph: float = 0.0,
    ) -> bool:
        """Suprime plan STATION: dwell, rollo sin puertas, o salida con tracción."""
        if self.state == "STOPPED":
            return True
        if self.state == "DEPARTING":
            return self._departing_suppresses_station_brake(
                station_dist_m=station_dist_m,
                speed_mph=speed_mph,
            )
        if self._pass_through:
            if station_dist_m is None or station_dist_m <= PLATFORM_AT_STOP_M:
                return True
            self._pass_through = False
        if (
            not self._doors_ever_opened
            and station_dist_m is not None
            and station_dist_m <= PLATFORM_AT_STOP_M
            and _live_roll_through_without_doors(
                speed_mph=speed_mph,
                throttle_notch=throttle_notch,
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
            elif station_departure_active(
                speed_mph=speed_mph,
                station_dist_m=station_dist_m,
                combined_lever=throttle_notch,
            ):
                self._enter_departing()

        self._clear_station_episode(station_dist_m)

    def _enter_departing(self) -> None:
        self._pass_through = not self._doors_opened
        self.state = "DEPARTING"
        self._departing_at = time.monotonic()
        self._doors_opened = False


def station_dwell_brake_command(
    *,
    station_fsm: Optional[str],
    speed_mph: float,
    lever: Optional[int],
    station_dist_m: Optional[float],
) -> Optional["BrakeCommand"]:
    """
    Mando dwell: B1 en ``STOPPED`` (puertas TSW).

    RELEASE en ``DEPARTING`` lo hace ``decision._attempt_departing_brake_release``.
    """
    from tsw6v2.command import platform_door_brake_command

    if station_fsm == "STOPPED":
        return platform_door_brake_command(distance_m=station_dist_m)
    return None
