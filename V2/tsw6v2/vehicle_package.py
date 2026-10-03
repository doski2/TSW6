"""Resolución de ``data/vehicles/<id>.json`` para modo IPC (323 muesca vs MC analog)."""

from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from tsw6v2.command import BrakeCommand

from tsw6v2.brake_air_profile import (
    MODEL_MASTER_CONTROLLER,
    MODEL_UK_EMU,
    BrakeAirProfile,
)
from tsw6v2.bridge.commands import (
    combined_notch_to_value,
    master_controller_input_value,
)
from tsw6v2.constants import B1_NOTCH, NEUTRAL_NOTCH
from tsw6v2.target import SERVICE_HANDLES_WEAK_TO_STRONG

_PACKAGE_SCHEMA = "tsw6-vehicle-package/1"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_vehicles_dir() -> Path:
    return repo_root() / "data" / "vehicles"


def vehicle_class_matches(probe_vehicle: str, package_class: str) -> bool:
    probe = (probe_vehicle or "").strip()
    klass = (package_class or "").strip()
    if not probe or not klass:
        return False
    if probe == klass:
        return True
    return klass in probe or probe.startswith(klass)


def uses_mc_analog_ipc(package: Optional[dict[str, Any]]) -> bool:
    if not package:
        return False
    layout = str(package.get("layout") or "")
    if layout == "master_controller":
        return True
    aliases = package.get("ipc_aliases") or {}
    return str(aliases.get("PowerBrakeHandle") or "") == "MasterController"


def resolve_brake_air_profile(
    package: Optional[dict[str, Any]],
) -> BrakeAirProfile:
    """L4 aire: explícito en ``brake_air.model`` o inferido de layout MC."""
    if not package:
        return BrakeAirProfile.uk_emu()
    block = package.get("brake_air")
    if isinstance(block, dict):
        model = str(block.get("model") or "").strip()
        if model in (MODEL_UK_EMU, MODEL_MASTER_CONTROLLER):
            return BrakeAirProfile(model=model)
    if uses_mc_analog_ipc(package):
        return BrakeAirProfile(model=MODEL_MASTER_CONTROLLER)
    return BrakeAirProfile.uk_emu()


@lru_cache(maxsize=1)
def _load_all_packages(vehicles_dir: str) -> tuple[tuple[str, dict[str, Any]], ...]:
    root = Path(vehicles_dir)
    if not root.is_dir():
        return ()
    out: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("schema") or "") != _PACKAGE_SCHEMA:
            continue
        out.append((path.name, data))
    return tuple(out)


def resolve_vehicle_package(
    probe_vehicle: str,
    *,
    vehicles_dir: Path | None = None,
) -> Optional[dict[str, Any]]:
    """Paquete G-B cuyo ``match.vehicle_class`` encaja con GetData ``vehicle=``."""
    text = (probe_vehicle or "").strip()
    if not text or text == "?":
        return None
    vdir = vehicles_dir or default_vehicles_dir()
    for _name, pkg in _load_all_packages(str(vdir.resolve())):
        match = pkg.get("match") or {}
        klass = str(match.get("vehicle_class") or "")
        if vehicle_class_matches(text, klass):
            return pkg
    return None


def _uk_map_from_package(package: dict[str, Any]) -> dict[int, float]:
    raw = package.get("uk_combined_notch_ipc") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[int, float] = {}
    for key, val in raw.items():
        try:
            out[int(key)] = float(val)
        except (TypeError, ValueError):
            continue
    return out


# OBSERVATION lab M3a 20261003 — hasta matriz F5 HUD↔InputValue en el paquete.
_FALLBACK_MC_UK_FRACTION: dict[int, float] = {
    B1_NOTCH: 0.85,
    NEUTRAL_NOTCH: 0.72,
}


def ipc_fraction_for_plan(
    *,
    phase: str,
    handle_notch: int,
    package: Optional[dict[str, Any]],
) -> Optional[float]:
    """Fracción cabina para fase de servicio (B1…) o muesca UK de respaldo."""
    if not package or not uses_mc_analog_ipc(package):
        return None
    ph = (phase or "").strip().upper()
    if ph in ("B1", "B2", "B3"):
        for notch, label in SERVICE_HANDLES_WEAK_TO_STRONG:
            if label == ph:
                return combined_notch_to_ipc_value(int(notch), package)
    return combined_notch_to_ipc_value(int(handle_notch), package)


def apply_vehicle_brake_actuator(
    cmd: BrakeCommand,
    package: Optional[dict[str, Any]],
) -> BrakeCommand:
    """
    Añade ``target_fraction`` en layout MC (planificación en valores de cabina).

    El plan interno puede seguir en fases B1/B2; la muesca UK solo alimenta learner/323.
    """
    if cmd.target_fraction is not None:
        return cmd
    if not package or not uses_mc_analog_ipc(package):
        return cmd
    if cmd.kind not in ("APPLY", "RELEASE"):
        return cmd
    notch = cmd.target_notch
    if cmd.kind == "RELEASE":
        n = int(notch) if notch is not None else NEUTRAL_NOTCH
        frac = combined_notch_to_ipc_value(n, package)
        return replace(cmd, target_fraction=frac)
    if notch is None and not cmd.phase:
        return cmd
    n = int(notch) if notch is not None else NEUTRAL_NOTCH
    frac = ipc_fraction_for_plan(phase=cmd.phase or "", handle_notch=n, package=package)
    if frac is None:
        return cmd
    return replace(cmd, target_fraction=frac)


def enrich_brake_command_actuator(
    cmd: BrakeCommand,
    package: Optional[dict[str, Any]],
) -> BrakeCommand:
    """Compat tests — preferir ``apply_vehicle_brake_actuator`` en producto."""
    return apply_vehicle_brake_actuator(cmd, package)


def combined_notch_to_ipc_value(
    notch: int,
    package: Optional[dict[str, Any]] = None,
) -> float:
    """Valor en línea ``PowerBrakeHandle`` (323: muesca/8; MC: fracción cabina)."""
    n = int(notch)
    if package and uses_mc_analog_ipc(package):
        mapped = _uk_map_from_package(package)
        if n in mapped:
            return master_controller_input_value(mapped[n])
        if n in _FALLBACK_MC_UK_FRACTION:
            return master_controller_input_value(_FALLBACK_MC_UK_FRACTION[n])
    return combined_notch_to_value(n)


def clear_package_cache() -> None:
    _load_all_packages.cache_clear()
