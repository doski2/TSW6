#!/usr/bin/env python3
"""Tipos compartidos frenado v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from tsw6.braking.v2.command import BrakeCommand, clamp_brake_handle

BrakeTargetKind = Literal["SPEED_LIMIT", "STATION", "SIGNAL"]

# Handle UK servicio: 3=B1 (suave) … 1=B3 (fuerte)
SERVICE_HANDLES_WEAK_TO_STRONG: tuple[tuple[int, str], ...] = (
    (3, "B1"),
    (2, "B2"),
    (1, "B3"),
)


@dataclass
class BrakeTargetResult:
    """Resultado de un planificador por objetivo (antes de prioridad)."""

    target_kind: BrakeTargetKind
    distance_m: float
    target_speed_mph: float
    handle_notch: int
    phase: str
    dist_start: float
    apply_now: bool
    detail: str = ""

    @property
    def urgency(self) -> float:
        """Menor dist_start = frenar antes (Dastsc)."""
        return self.dist_start

    def to_brake_command(
        self,
        *,
        throttle_notch: int = 0,
        current_notch: int = 4,
        speed_mph: float = 0.0,
    ) -> Optional[BrakeCommand]:
        if not self.apply_now and self.dist_start > 60:
            return None
        if throttle_notch > 0 or current_notch > 4:
            return BrakeCommand(
                kind="COAST_THROTTLE",
                target_notch=4,
                reason="Soltar tracción antes de freno",
            )
        if (
            self.target_kind == "STATION"
            and current_notch < 4
            and speed_mph <= self.target_speed_mph + 2.0
        ):
            return BrakeCommand(
                kind="RELEASE",
                target_notch=4,
                phase="NEU",
                reason="Parada en andén",
            )
        handle = clamp_brake_handle(self.handle_notch, self.distance_m)
        return BrakeCommand(
            kind="APPLY",
            target_notch=handle,
            phase=self.phase,
            reason=self.detail or f"{self.phase} distStart={self.dist_start:.0f}m",
            distance_m=self.distance_m,
        )
