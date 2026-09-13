"""Tipos y constantes del plan cartel (antes de mandos IPC)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

from tsw6v2.constants import (
    LIMIT_COAST_BAND_MPH,
    LIMIT_CONTAIN_ESCALATE_OVER_MPH,
    LIMIT_SCORING_MAX_OVER_MPH,
    LIMIT_SIGN_PASSED_M,
)

if TYPE_CHECKING:
    from tsw6v2.command import BrakeCommand

BrakeTargetKind = Literal["SPEED_LIMIT", "STATION", "SIGNAL"]

# Handle UK servicio: 3=B1 (suave) … 1=B3 (fuerte)
SERVICE_HANDLES_WEAK_TO_STRONG: tuple[tuple[int, str], ...] = (
    (3, "B1"),
    (2, "B2"),
    (1, "B3"),
)


@dataclass
class BrakeTargetResult:
    """Resultado de un planificador por objetivo (antes de mandos)."""

    target_kind: BrakeTargetKind
    distance_m: float
    target_speed_mph: float
    handle_notch: int
    phase: str
    dist_start: float
    apply_now: bool
    detail: str = ""
    downhill_hold: bool = False
    coast_trim_deferred: bool = False
    fb_a_pred_ms2: Optional[float] = None
    fb_a_obs_ms2: Optional[float] = None
    fb_shortfall: bool = False
    fb_escalated: bool = False

    @property
    def urgency(self) -> float:
        """Menor dist_start = frenar antes."""
        return self.dist_start

    def to_brake_command(
        self,
        *,
        throttle_notch: int = 0,
        current_notch: int = 4,
        speed_mph: float = 0.0,
        gradient_pct: float = 0.0,
        brake_committed: bool = False,
    ) -> Optional["BrakeCommand"]:
        if self.target_kind in ("STATION", "SIGNAL"):
            from tsw6v2.service_brake import command_from_stop_target

            return command_from_stop_target(
                self,
                throttle_notch=throttle_notch,
                current_notch=current_notch,
                speed_mph=speed_mph,
                gradient_pct=gradient_pct,
            )

        from tsw6v2.command import command_from_target

        return command_from_target(
            target_kind=self.target_kind,
            distance_m=self.distance_m,
            target_speed_mph=self.target_speed_mph,
            handle_notch=self.handle_notch,
            phase=self.phase,
            dist_start=self.dist_start,
            apply_now=self.apply_now,
            throttle_notch=throttle_notch,
            current_notch=current_notch,
            speed_mph=speed_mph,
            apply_at_remaining_m=self.distance_m - self.dist_start,
            detail=self.detail,
            gradient_pct=gradient_pct,
            brake_committed=brake_committed,
            coast_trim_deferred=self.coast_trim_deferred,
        )


__all__ = [
    "BrakeTargetKind",
    "BrakeTargetResult",
    "LIMIT_COAST_BAND_MPH",
    "LIMIT_CONTAIN_ESCALATE_OVER_MPH",
    "LIMIT_SCORING_MAX_OVER_MPH",
    "LIMIT_SIGN_PASSED_M",
    "SERVICE_HANDLES_WEAK_TO_STRONG",
]
