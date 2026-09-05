"""Estado y latch del plan cartel (decel por muesca, margen reacción)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from tsw6v2.physics import (
    DEFAULT_BRAKE_FILL_S,
    MPH_TO_MS,
    brake_reaction_margin_m,
)
from tsw6v2.plan import (
    SERVICE_DECEL_FRAC_BY_HANDLE,
    UK_SERVICE_PHASES,
    resolve_phase_decel,
)
from tsw6v2.constants import passenger_ops_target_mph
from tsw6v2.target import SERVICE_HANDLES_WEAK_TO_STRONG

PredictDecelFn = Callable[[int, float, float], Optional[float]]

LIMIT_REACTION_S = 1.5


@dataclass
class LimitBrakeLatch:
    """Constantes fijadas al recibir el cartel."""

    posted_limit_mph: float
    limit_mph: float  # techo operativo (posted − margen pasajero)
    distance_m: float
    latched_speed_mph: float
    gradient_pct: float
    accel_ms2: Optional[float]
    decel_by_handle: dict[int, float]
    learned_by_handle: dict[int, bool]
    reaction_margin_m: float


@dataclass
class LimitBrakeState:
    latch: Optional[LimitBrakeLatch] = None
    last_limit_mph: Optional[float] = None
    committed_handle: Optional[int] = None
    committed_phase: Optional[str] = None

    def reset(self) -> None:
        self.latch = None
        self.last_limit_mph = None
        self.committed_handle = None
        self.committed_phase = None


def limit_changed(
    prev: Optional[float],
    new: float,
    tolerance_mph: float = 2.0,
) -> bool:
    if prev is None:
        return True
    return abs(prev - new) > tolerance_mph


def decel_for_handle(
    handle: int,
    speed_mph: float,
    gradient_pct: float,
    base_decel: float,
    predict_decel: Optional[PredictDecelFn],
) -> tuple[float, bool]:
    """(decel m/s², using_learned). Aprendido ya incluye grado."""
    phase = next((p for p in UK_SERVICE_PHASES if p.handle_notch == handle), None)
    if phase is None:
        frac = SERVICE_DECEL_FRAC_BY_HANDLE.get(handle, 0.80)
        return max(base_decel * frac, 0.05), False
    return resolve_phase_decel(
        phase, speed_mph, gradient_pct, base_decel, predict_decel)


def latch_limit_target(
    state: LimitBrakeState,
    *,
    posted_limit_mph: float,
    distance_m: float,
    speed_mph: float,
    gradient_pct: float,
    accel_ms2: Optional[float],
    base_decel: float,
    predict_decel: Optional[PredictDecelFn],
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
) -> LimitBrakeLatch:
    ops_target_mph = passenger_ops_target_mph(posted_limit_mph)
    speed_ms = speed_mph * MPH_TO_MS
    decel_by_handle: dict[int, float] = {}
    learned_by_handle: dict[int, bool] = {}
    for handle, _ in SERVICE_HANDLES_WEAK_TO_STRONG:
        d, learned = decel_for_handle(
            handle, speed_mph, gradient_pct, base_decel, predict_decel)
        decel_by_handle[handle] = d
        learned_by_handle[handle] = learned

    latch = LimitBrakeLatch(
        posted_limit_mph=posted_limit_mph,
        limit_mph=ops_target_mph,
        distance_m=distance_m,
        latched_speed_mph=speed_mph,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
        decel_by_handle=decel_by_handle,
        learned_by_handle=learned_by_handle,
        reaction_margin_m=brake_reaction_margin_m(
            speed_ms,
            brake_fill_s=brake_fill_s,
            reaction_base_s=LIMIT_REACTION_S,
        ),
    )
    state.latch = latch
    state.last_limit_mph = posted_limit_mph
    return latch


def refresh_latch_physics(
    latch: LimitBrakeLatch,
    *,
    speed_mph: float,
    gradient_pct: float,
    accel_ms2: Optional[float],
    base_decel: float,
    predict_decel: Optional[PredictDecelFn],
    brake_fill_s: float,
) -> None:
    """Cada tick: a, pendiente y reacción con la velocidad actual."""
    latch.gradient_pct = gradient_pct
    latch.accel_ms2 = accel_ms2
    latch.latched_speed_mph = speed_mph
    latch.reaction_margin_m = brake_reaction_margin_m(
        speed_mph * MPH_TO_MS,
        brake_fill_s=brake_fill_s,
        reaction_base_s=LIMIT_REACTION_S,
    )
    for handle, _ in SERVICE_HANDLES_WEAK_TO_STRONG:
        d, learned = decel_for_handle(
            handle, speed_mph, gradient_pct, base_decel, predict_decel)
        latch.decel_by_handle[handle] = d
        latch.learned_by_handle[handle] = learned
