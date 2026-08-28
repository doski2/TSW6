#!/usr/bin/env python3
"""
tsw_command_bus.py — Envío de FRENOS vía API TSW directa (V2).

Patrón inspirado en Dastsc command_bus: allowlist, clamp, dispatch → ack.
Solo frenos — tracción y emergencia bloqueados en esta versión.
"""

from __future__ import annotations

from typing import Any, Optional

from tsw6.telemetry.tsw_api_client import TswApiClient

# Rutas TSW permitidas para escritura de freno (V2)
_ALLOWED_BRAKE_PATHS = frozenset({
    "PowerBrakeHandle",
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

# Ejes lógicos → ruta API por defecto (sin schema)
LOGICAL_BRAKE_AXES = frozenset({
    "combined_brake",
    "train_brake",
    "ind_brake",
    "dyn_brake",
})

DEFAULT_TSW_PATHS: dict[str, str] = {
    "combined_brake": "PowerBrakeHandle",
    "train_brake": "AutomaticBrake",
    "ind_brake": "IndependentBrake",
    "dyn_brake": "DynamicBrake",
}

# Handle UK 0–8 → IPC cmd 0.0–1.0 (misma escala que HandleController / SendCommand)
_COMBINED_NOTCH_MAX = 8
_NEUTRAL_NOTCH = 4

# PowerBrakeHandle.InputValue (Class 323). Peldaños de
# LiahMartens/tsw-controller-app shared-profiles/class323.tswprofile
# (DirectControl min=-0.6 max=1). Notch 0 (emergencia HUD) no está en ese
# perfil; se escribe -1.0. Tracción 5–8 coincide con 0.25/0.5/0.75/1.
CLASS323_PBH_INPUT_BY_NOTCH: tuple[float, ...] = (
    -1.0,   # 0 emergencia
    -0.6,   # 1 B3
    -0.4,   # 2 B2
    -0.2,   # 3 B1
    0.0,    # 4 neutro
    0.25,   # 5 P1
    0.5,    # 6 P2
    0.75,   # 7 P3
    1.0,    # 8 P4
)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def clamp_brake_value(control_path: str, value: float) -> float:
    """Acota valor según tipo de mando."""
    path = control_path.strip()
    if path == "IndependentBrake":
        return _clamp(value, -1.0, 1.0)
    if path in ("PowerBrakeHandle", "AutomaticBrake", "DynamicBrake",
                "TrainBrake", "LocomotiveBrake"):
        return _clamp(value, 0.0, 1.0)
    return _clamp(value, -1.0, 1.0)


def is_allowed_brake_path(control_path: str, schema: Optional[dict] = None) -> bool:
    name = str(control_path or "").strip()
    if not name or name in _BLOCKED_PATHS:
        return False
    if name in _ALLOWED_BRAKE_PATHS:
        return True
    if schema:
        paths = schema.get("tsw_api_paths") or {}
        if name in paths.values():
            return True
    return False


def resolve_brake_path(
    control: str,
    schema: Optional[dict] = None,
) -> Optional[str]:
    """
    Resuelve eje lógico (combined_brake) o ruta API (PowerBrakeHandle).
    """
    key = str(control or "").strip()
    if not key:
        return None

    paths = (schema or {}).get("tsw_api_paths") or {}
    if key in LOGICAL_BRAKE_AXES:
        resolved = paths.get(key) or DEFAULT_TSW_PATHS.get(key)
        return str(resolved).strip() if resolved else None

    if key in _ALLOWED_BRAKE_PATHS:
        return key
    if key in paths.values():
        return key
    return None


def combined_notch_to_value(notch: int) -> float:
    """Muesca handle UK 0–8 → valor API 0.0–1.0."""
    n = max(0, min(_COMBINED_NOTCH_MAX, int(notch)))
    return n / float(_COMBINED_NOTCH_MAX)


def combined_notch_to_axis(notch: int) -> float:
    """Muesca handle UK 0–8 → InputValue Class 323 (detents Liah)."""
    n = max(0, min(_COMBINED_NOTCH_MAX, int(notch)))
    return float(CLASS323_PBH_INPUT_BY_NOTCH[n])


def combined_axis_to_notch(axis: float) -> int:
    """InputValue Class 323 → muesca 0–8 más cercana."""
    v = float(axis)
    best = 0
    best_d = abs(v - CLASS323_PBH_INPUT_BY_NOTCH[0])
    for i, det in enumerate(CLASS323_PBH_INPUT_BY_NOTCH):
        d = abs(v - det)
        if d < best_d:
            best_d = d
            best = i
    return best


def combined_value_to_notch(value: float) -> int:
    """Valor IPC 0..1 (notch/8) → muesca entera más cercana."""
    v = _clamp(value, 0.0, 1.0)
    return int(round(v * _COMBINED_NOTCH_MAX))


def neutral_combined_value() -> float:
    return combined_notch_to_value(_NEUTRAL_NOTCH)


def dispatch_brake(
    client: TswApiClient,
    control: str,
    value: float,
    schema: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> dict[str, Any]:
    """
    Valida y envía un mando de freno.

    `control` puede ser eje lógico (combined_brake) o ruta API (PowerBrakeHandle).
    """
    key = str(control or "").strip()
    if key in _BLOCKED_PATHS:
        return {"ok": False, "error": "command_not_allowed", "control": control}

    path = resolve_brake_path(control, schema)
    if not path:
        return {"ok": False, "error": "unknown_control", "control": control}

    if not is_allowed_brake_path(path, schema):
        return {"ok": False, "error": "command_not_allowed", "control": control, "path": path}

    clamped = clamp_brake_value(path, value)
    if path == "PowerBrakeHandle":
        target_notch = combined_value_to_notch(clamped)
        axis = combined_notch_to_axis(target_notch)
        result: dict[str, Any] = {"ok": False, "error": "no_attempt", "path": path}
        for via, attempt in (
            ("input", lambda: client.set_input_value(path, axis, timeout=timeout)),
            ("value", lambda: client.set_value(path, clamped, timeout=timeout)),
        ):
            attempt_result = attempt()
            if not attempt_result.get("ok"):
                result = attempt_result
                continue
            hud = client.read_hud_combined_notch()
            if hud is not None and abs(int(hud) - int(target_notch)) <= 1:
                result = attempt_result
                result["via"] = via
                result["hud_notch"] = int(hud)
                result["target_notch"] = int(target_notch)
                break
            result = {
                "ok": False,
                "error": "hud_no_effect",
                "path": path,
                "value": clamped,
                "axis": axis,
                "via": via,
                "hud_notch": hud,
                "target_notch": int(target_notch),
            }
    else:
        result = client.set_value(path, clamped, timeout=timeout)
    result["control"] = control
    result["path"] = path
    if result.get("ok"):
        result["value"] = clamped
    return result


def dispatch_combined_notch(
    client: TswApiClient,
    notch: int,
    schema: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> dict[str, Any]:
    """Atajo UK: envía muesca 0–8 al handle combinado."""
    return dispatch_brake(
        client,
        "combined_brake",
        combined_notch_to_value(notch),
        schema,
        timeout=timeout,
    )
