#!/usr/bin/env python3
"""
tsw_ipc_bus.py — Escritura de mandos vía SendCommand.txt (TelemetryProbeMod / B4).

Patrón Dastsc: allowlist + clamp + archivo atómico + flag de armado.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from tsw6.telemetry.tsw_command_bus import (
    clamp_brake_value,
    combined_notch_to_value,
    is_allowed_brake_path,
    neutral_combined_value,
    resolve_brake_path,
)

_BLOCKED_PATHS = frozenset({
    "EmergencyBrake",
    "emergency_brake",
    "Reverser",
    "UserVirtualReverser",
    "MasterKey",
    "Throttle",
})

SEND_COMMAND_FILENAME = "SendCommand.txt"
APPLY_FLAG_FILENAME = "TSW6ApplyCommands.flag"
SEND_ACK_FILENAME = "SendCommandAck.txt"

ACK_TIMEOUT_MIN_S = 0.05
ACK_TIMEOUT_MAX_S = 0.12
DEFAULT_FRAME_BUDGET = 3.5
DEFAULT_ASSUMED_FPS = 55.0


def adaptive_ack_timeout_s(
    recent_ack_ms: Optional[list[float]] = None,
    *,
    assumed_fps: float = DEFAULT_ASSUMED_FPS,
    frame_budget: float = DEFAULT_FRAME_BUDGET,
) -> float:
    """Timeout ACK adaptativo: 2–4 frames @ FPS + margen sobre p95 reciente."""
    fps = max(30.0, min(120.0, float(assumed_fps)))
    frame_s = frame_budget / fps
    timeout = frame_s
    samples = list(recent_ack_ms or [])
    if samples:
        ordered = sorted(samples[-20:])
        idx = max(0, int(len(ordered) * 0.95) - 1)
        p95 = ordered[idx]
        timeout = max(timeout, (p95 * 1.5) / 1000.0)
    return max(ACK_TIMEOUT_MIN_S, min(ACK_TIMEOUT_MAX_S, timeout))


def parse_send_ack_line(line: str) -> Optional[dict[str, Any]]:
    """Parsea ACK Lua: ``path:value:ok`` o ``path:value:ok:cmd_id``."""
    parts = line.strip().split(":")
    if len(parts) < 3:
        return None
    cmd_id: Optional[int] = None
    if len(parts) >= 4 and parts[-1].strip().isdigit():
        cmd_id = int(parts[-1].strip())
        status = parts[-2].strip().lower()
        val = float(parts[-3])
        name = ":".join(parts[:-3])
    else:
        status = parts[-1].strip().lower()
        val = float(parts[-2])
        name = ":".join(parts[:-2])
    return {
        "name": name,
        "value": val,
        "ok": status == "ok",
        "cmd_id": cmd_id,
    }


def bridge_dir() -> Path:
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    return Path(temp) / "TSW6Bridge"


def send_command_path() -> Path:
    return bridge_dir() / SEND_COMMAND_FILENAME


def apply_flag_path() -> Path:
    return bridge_dir() / APPLY_FLAG_FILENAME


def enable_lua_commands() -> None:
    """Lua solo aplica SendCommand si existe el flag (evita mandos huérfanos)."""
    bridge_dir().mkdir(parents=True, exist_ok=True)
    apply_flag_path().write_text("1\n", encoding="utf-8")


def purge_lua_commands() -> bool:
    """Elimina SendCommand + flag huérfanos."""
    removed = False
    for path in (send_command_path(), apply_flag_path(), send_ack_path()):
        try:
            if path.is_file():
                path.unlink()
                removed = True
        except OSError:
            pass
    return removed


def format_send_command_line(
    control: str,
    value: float,
    schema: Optional[dict] = None,
    *,
    cmd_id: Optional[int] = None,
) -> str:
    path = resolve_brake_path(control, schema)
    if not path:
        raise ValueError(f"unknown control: {control}")
    clamped = clamp_brake_value(path, value)
    if cmd_id is not None:
        return f"{path}:{clamped:.4f}:{int(cmd_id)}"
    return f"{path}:{clamped:.4f}"


def send_ack_path() -> Path:
    return bridge_dir() / SEND_ACK_FILENAME


def _clear_send_ack() -> None:
    """Elimina ack viejo para no confundirlo con el mando actual."""
    path = send_ack_path()
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def wait_send_ack(
    timeout_s: float = 0.12,
    *,
    expected_path: Optional[str] = None,
    expected_value: Optional[float] = None,
    expected_cmd_id: Optional[int] = None,
    value_tol: float = 0.0005,
) -> Optional[dict[str, Any]]:
    """Espera SendCommandAck.txt escrito por Lua tras aplicar el mando."""
    path = send_ack_path()
    deadline = time.monotonic() + max(0.02, float(timeout_s))
    while time.monotonic() < deadline:
        try:
            if path.is_file():
                line = path.read_text(encoding="utf-8").strip()
                if line:
                    ack = parse_send_ack_line(line)
                    if ack is None:
                        time.sleep(0.008)
                        continue
                    if expected_path and ack["name"] != expected_path:
                        time.sleep(0.008)
                        continue
                    if (
                        expected_value is not None
                        and abs(float(ack["value"]) - expected_value) > value_tol
                    ):
                        time.sleep(0.008)
                        continue
                    if (
                        expected_cmd_id is not None
                        and ack.get("cmd_id") is not None
                        and int(ack["cmd_id"]) != int(expected_cmd_id)
                    ):
                        time.sleep(0.008)
                        continue
                    return ack
        except (OSError, ValueError):
            pass
        time.sleep(0.008)
    return None


def write_send_command(
    control: str,
    value: float,
    schema: Optional[dict] = None,
    *,
    cmd_id: Optional[int] = None,
) -> bool:
    """Escribe SendCommand.txt de forma atómica. Devuelve False si falla validación o I/O."""
    path_name = resolve_brake_path(control, schema)
    if not path_name or not is_allowed_brake_path(path_name, schema):
        return False
    clamped = clamp_brake_value(path_name, value)
    line = format_send_command_line(control, clamped, schema, cmd_id=cmd_id)
    directory = bridge_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".sendcmd_", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as tmp:
                tmp.write(line + "\n")
            os.replace(tmp_path, send_command_path())
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        enable_lua_commands()
        return True
    except OSError:
        return False


def write_send_command_with_ack(
    control: str,
    value: float,
    schema: Optional[dict] = None,
    *,
    ack_timeout_s: float = 0.12,
    cmd_id: Optional[int] = None,
) -> dict[str, Any]:
    """Escribe SendCommand y espera confirmación Lua."""
    t0 = time.perf_counter()
    path_name = resolve_brake_path(control, schema)
    if not path_name or not is_allowed_brake_path(path_name, schema):
        return {"ok": False, "error": "invalid_control", "control": control,
                "ack_ms": 0.0}
    clamped = clamp_brake_value(path_name, value)
    _clear_send_ack()
    if not write_send_command(control, clamped, schema, cmd_id=cmd_id):
        return {"ok": False, "error": "write_failed", "control": control,
                "path": path_name, "value": clamped, "ack_ms": 0.0}
    ack = wait_send_ack(
        ack_timeout_s,
        expected_path=path_name,
        expected_value=clamped,
        expected_cmd_id=cmd_id,
    )
    ack_ms = (time.perf_counter() - t0) * 1000.0
    if ack is None:
        return {"ok": False, "error": "ack_timeout", "control": control,
                "path": path_name, "value": clamped, "ack_ms": ack_ms}
    if not ack.get("ok"):
        return {"ok": False, "error": "lua_rejected", "control": control,
                "path": path_name, "value": clamped, "ack": ack,
                "ack_ms": ack_ms}
    return {
        "ok": True,
        "control": control,
        "path": path_name,
        "value": clamped,
        "channel": "ipc",
        "ack_ms": ack_ms,
        "ack": ack,
    }


def dispatch_ipc_brake(
    control: str,
    value: float,
    schema: Optional[dict] = None,
    *,
    wait_ack: bool = True,
    cmd_id: Optional[int] = None,
    ack_timeout_s: float = 0.12,
) -> dict[str, Any]:
    """Valida y escribe un mando de freno al bridge IPC."""
    key = str(control or "").strip()
    if key in _BLOCKED_PATHS:
        return {"ok": False, "error": "command_not_allowed", "control": control}
    path_name = resolve_brake_path(control, schema)
    if not path_name:
        return {"ok": False, "error": "unknown_control", "control": control}
    if not is_allowed_brake_path(path_name, schema):
        return {"ok": False, "error": "command_not_allowed", "control": control}
    clamped = clamp_brake_value(path_name, value)
    if wait_ack:
        return write_send_command_with_ack(
            control, clamped, schema,
            ack_timeout_s=ack_timeout_s,
            cmd_id=cmd_id,
        )
    if not write_send_command(control, clamped, schema, cmd_id=cmd_id):
        return {"ok": False, "error": "write_failed", "control": control}
    return {
        "ok": True,
        "control": control,
        "path": path_name,
        "value": clamped,
        "channel": "ipc",
    }


def dispatch_ipc_combined_notch(
    notch: int,
    schema: Optional[dict] = None,
    *,
    cmd_id: Optional[int] = None,
    ack_timeout_s: float = 0.12,
) -> dict[str, Any]:
    return dispatch_ipc_brake(
        "combined_brake",
        combined_notch_to_value(notch),
        schema,
        cmd_id=cmd_id,
        ack_timeout_s=ack_timeout_s,
    )


def release_controls(wait_s: float = 0.15) -> bool:
    """Mando neutro + purga IPC (salida segura del autopilot)."""
    ok = write_send_command("combined_brake", neutral_combined_value())
    if wait_s > 0:
        time.sleep(wait_s)
    purge_lua_commands()
    return ok
