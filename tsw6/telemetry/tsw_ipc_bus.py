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
    for path in (send_command_path(), apply_flag_path()):
        try:
            if path.is_file():
                path.unlink()
                removed = True
        except OSError:
            pass
    return removed


def format_send_command_line(control: str, value: float,
                             schema: Optional[dict] = None) -> str:
    path = resolve_brake_path(control, schema)
    if not path:
        raise ValueError(f"unknown control: {control}")
    clamped = clamp_brake_value(path, value)
    return f"{path}:{clamped:.4f}"


def write_send_command(
    control: str,
    value: float,
    schema: Optional[dict] = None,
) -> bool:
    """Escribe SendCommand.txt de forma atómica. Devuelve False si falla validación o I/O."""
    path_name = resolve_brake_path(control, schema)
    if not path_name or not is_allowed_brake_path(path_name, schema):
        return False
    clamped = clamp_brake_value(path_name, value)
    line = f"{path_name}:{clamped:.4f}"
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


def dispatch_ipc_brake(
    control: str,
    value: float,
    schema: Optional[dict] = None,
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
    if not write_send_command(control, clamped, schema):
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
) -> dict[str, Any]:
    return dispatch_ipc_brake(
        "combined_brake",
        combined_notch_to_value(notch),
        schema,
    )


def release_controls(wait_s: float = 0.15) -> bool:
    """Mando neutro + purga IPC (salida segura del autopilot)."""
    ok = write_send_command("combined_brake", neutral_combined_value())
    if wait_s > 0:
        time.sleep(wait_s)
    purge_lua_commands()
    return ok
