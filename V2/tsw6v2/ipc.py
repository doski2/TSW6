"""IPC multi-paso hacia muesca combinada (Class 323) o fracción MC (MasterController)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from tsw6v2.bridge.getdata import (
    ProbeSnapshot,
    default_getdata_path,
    read_probe_file,
)
from tsw6v2.bridge.ipc_bus import (
    dispatch_ipc_combined_notch,
    dispatch_ipc_master_controller,
    enable_lua_commands,
)
from tsw6v2.vehicle_package import (
    combined_notch_to_ipc_value,
    resolve_vehicle_package,
    uses_mc_analog_ipc,
)

DEFAULT_ACK_TIMEOUT_S = 0.35
DEFAULT_MAX_STEPS = 9
DEFAULT_STEP_PAUSE_S = 0.08
DEFAULT_STEP_WAIT_S = 0.6


def ipc_steps_needed(current: int, target: int) -> int:
    return abs(int(current) - int(target))


def probe_lever(snap: Optional[ProbeSnapshot]) -> Optional[int]:
    if snap is None:
        return None
    return snap.combined_handle_notch()


def _vehicle_id_from_probe(snap: Optional[ProbeSnapshot]) -> Optional[str]:
    if snap is None:
        return None
    v = (snap.vehicle or "").strip()
    if not v or v == "?":
        return None
    return v


def _package_for_vehicle(
    vehicle: Optional[str],
    vehicle_package: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if vehicle_package is not None:
        return vehicle_package
    if vehicle:
        return resolve_vehicle_package(vehicle)
    return None


def dispatch_to_input_fraction(
    fraction: float,
    *,
    cmd_id: int,
    ack_timeout_s: float = 0.12,
) -> dict[str, Any]:
    """Un paso IPC hacia fracción 0..1 (MasterController / analógico)."""
    enable_lua_commands()
    return dispatch_ipc_master_controller(
        fraction,
        cmd_id=cmd_id,
        ack_timeout_s=ack_timeout_s,
    )


def dispatch_step_toward_notch(
    target: int,
    *,
    cmd_id: int,
    ack_timeout_s: float = 0.12,
    vehicle: Optional[str] = None,
    vehicle_package: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    pkg = _package_for_vehicle(vehicle, vehicle_package)
    enable_lua_commands()
    if pkg and uses_mc_analog_ipc(pkg):
        fraction = combined_notch_to_ipc_value(target, pkg)
        return dispatch_ipc_master_controller(
            fraction,
            cmd_id=cmd_id,
            ack_timeout_s=ack_timeout_s,
        )
    return dispatch_ipc_combined_notch(
        target,
        cmd_id=cmd_id,
        ack_timeout_s=ack_timeout_s,
    )


def drive_to_notch(
    target: int,
    *,
    path: Optional[Path] = None,
    cmd_id_start: int = 1,
    max_steps: int = DEFAULT_MAX_STEPS,
    ack_timeout_s: float = DEFAULT_ACK_TIMEOUT_S,
    step_pause_s: float = DEFAULT_STEP_PAUSE_S,
    step_wait_s: float = DEFAULT_STEP_WAIT_S,
    vehicle: Optional[str] = None,
    vehicle_package: Optional[dict[str, Any]] = None,
) -> tuple[bool, Optional[ProbeSnapshot], list[dict[str, Any]], int]:
    getdata = path or default_getdata_path()
    results: list[dict[str, Any]] = []
    cmd_id = cmd_id_start
    if vehicle is None:
        vehicle = _vehicle_id_from_probe(read_probe_file(getdata))
    pkg = _package_for_vehicle(vehicle, vehicle_package)
    mc_analog = pkg is not None and uses_mc_analog_ipc(pkg)
    step_limit = 1 if mc_analog else max_steps
    for _ in range(step_limit):
        snap = read_probe_file(getdata)
        if vehicle is None:
            vehicle = _vehicle_id_from_probe(snap)
            if vehicle:
                pkg = _package_for_vehicle(vehicle, vehicle_package)
                mc_analog = pkg is not None and uses_mc_analog_ipc(pkg)
        current = probe_lever(snap)
        if current is not None and int(current) == int(target):
            return True, snap, results, len(results)
        result = dispatch_step_toward_notch(
            target,
            cmd_id=cmd_id,
            ack_timeout_s=ack_timeout_s,
            vehicle=vehicle,
            vehicle_package=pkg,
        )
        results.append(result)
        cmd_id += 1
        if not result.get("ok"):
            return False, read_probe_file(getdata), results, len(results)
        if mc_analog:
            return True, read_probe_file(getdata), results, len(results)
        prev = current
        deadline = time.monotonic() + step_wait_s
        while time.monotonic() < deadline:
            snap = read_probe_file(getdata)
            lever = probe_lever(snap)
            if lever is not None and int(lever) == int(target):
                return True, snap, results, len(results)
            if lever is not None and prev is not None and int(lever) != int(prev):
                break
            time.sleep(0.05)
        time.sleep(step_pause_s)
    snap = read_probe_file(getdata)
    lever = probe_lever(snap)
    ok = lever is not None and int(lever) == int(target)
    return ok, snap, results, len(results)
