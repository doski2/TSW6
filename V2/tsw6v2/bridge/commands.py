"""Mapeo muesca combinada UK 0–8 → valor IPC (contrato CANAL_CONTROL § SendCommand)."""

from __future__ import annotations

from typing import Optional

NOTCH_MAX = 8
COMBINED_BRAKE = "combined_brake"
POWER_BRAKE_HANDLE = "PowerBrakeHandle"

_ALLOWED_PATHS = frozenset({
    POWER_BRAKE_HANDLE,
    "AutomaticBrake",
    "IndependentBrake",
    "DynamicBrake",
    "TrainBrake",
    "LocomotiveBrake",
})

_BLOCKED_PATHS = frozenset({
    "EmergencyBrake",
    "emergency_brake",
    "Reverser",
    "UserVirtualReverser",
    "MasterKey",
    "Throttle",
})

_DEFAULT_PATHS: dict[str, str] = {
    COMBINED_BRAKE: POWER_BRAKE_HANDLE,
    "train_brake": "AutomaticBrake",
    "ind_brake": "IndependentBrake",
    "dyn_brake": "DynamicBrake",
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def combined_notch_to_value(notch: int) -> float:
    """Muesca 0–8 → cmd normalizado 0.0–1.0 (Lua un paso ±1 hacia destino)."""
    n = max(0, min(NOTCH_MAX, int(notch)))
    return n / float(NOTCH_MAX)


def resolve_control_path(
    control: str,
    schema: Optional[dict] = None,
) -> Optional[str]:
    key = str(control or "").strip()
    if not key:
        return None
    paths = (schema or {}).get("tsw_api_paths") or {}
    if key in _DEFAULT_PATHS:
        resolved = paths.get(key) or _DEFAULT_PATHS[key]
        return str(resolved).strip() if resolved else None
    if key in _ALLOWED_PATHS:
        return key
    if key in paths.values():
        return key
    return None


def is_allowed_path(path: str, schema: Optional[dict] = None) -> bool:
    name = str(path or "").strip()
    if not name or name in _BLOCKED_PATHS:
        return False
    if name in _ALLOWED_PATHS:
        return True
    if schema:
        api_paths = schema.get("tsw_api_paths") or {}
        return name in api_paths.values()
    return False


def clamp_brake_value(path: str, value: float) -> float:
    if path == "IndependentBrake":
        return _clamp(value, -1.0, 1.0)
    if path in _ALLOWED_PATHS:
        return _clamp(value, 0.0, 1.0)
    return _clamp(value, -1.0, 1.0)
