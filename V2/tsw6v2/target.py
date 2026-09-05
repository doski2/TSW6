"""Re-export P1 target types (definidos en command.py)."""

from tsw6v2.command import (
    LIMIT_COAST_BAND_MPH,
    LIMIT_CONTAIN_ESCALATE_OVER_MPH,
    LIMIT_SCORING_MAX_OVER_MPH,
    LIMIT_SIGN_PASSED_M,
    SERVICE_HANDLES_WEAK_TO_STRONG,
    BrakeTargetKind,
    BrakeTargetResult,
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
