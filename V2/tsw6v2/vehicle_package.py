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


def vehicle_package_from_snap(
    snap: Any,
    vehicle_package: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Paquete ya cargado o resuelto desde ``snap.vehicle`` (evita duplicar en command/loop)."""
    if vehicle_package is not None:
        return vehicle_package
    if snap is None:
        return None
    return resolve_vehicle_package(str(getattr(snap, "vehicle", "") or ""))


def _normalize_brake_input_key(key: str) -> str:
    k = (key or "").strip().upper()
    if k in ("NEU", "COAST", "RELEASE"):
        return "NEUTRAL"
    return k


def profile_brake_fraction(
    package: Optional[dict[str, Any]],
    phase_or_slot: str,
) -> Optional[float]:
    """
    Fracción 0..1 en línea IPC para MC — **solo** desde ``brake_input`` del paquete.

    Claves: ``neutral``, ``B1``, ``B2``, ``B3`` (alias ``NEU`` → neutral).
    Si falta ``brake_input``, legado ``uk_combined_notch_ipc``.
    """
    if not package or not uses_mc_analog_ipc(package):
        return None
    norm = _normalize_brake_input_key(phase_or_slot)
    block = package.get("brake_input")
    if isinstance(block, dict):
        for raw_k, val in block.items():
            if _normalize_brake_input_key(str(raw_k)) != norm:
                continue
            try:
                return master_controller_input_value(float(val))
            except (TypeError, ValueError):
                return None
    return _legacy_mc_fraction_from_uk_map(package, norm)


def profile_neutral_fraction(
    package: Optional[dict[str, Any]],
) -> Optional[float]:
    """Neutro MC del paquete (feedback IPC / ``brake_applied_from_probe``)."""
    return profile_brake_fraction(package, "neutral")


def _legacy_mc_fraction_from_uk_map(
    package: dict[str, Any],
    norm_phase: str,
) -> Optional[float]:
    """``uk_combined_notch_ipc`` — solo migración; preferir ``brake_input``."""
    raw = package.get("uk_combined_notch_ipc") or {}
    if not isinstance(raw, dict):
        return None
    if norm_phase == "NEUTRAL":
        key = str(NEUTRAL_NOTCH)
    else:
        key = None
        for notch, label in SERVICE_HANDLES_WEAK_TO_STRONG:
            if label == norm_phase:
                key = str(int(notch))
                break
        if key is None:
            return None
    if key not in raw:
        return None
    try:
        return master_controller_input_value(float(raw[key]))
    except (TypeError, ValueError):
        return None


def mc_fraction_for_plan_handle(
    package: Optional[dict[str, Any]],
    *,
    phase: str,
    handle_notch: int,
) -> Optional[float]:
    """Plan P1 (fases B* / muesca lógica UK) → fracción perfil en MC."""
    if not package or not uses_mc_analog_ipc(package):
        return None
    ph = (phase or "").strip().upper()
    if ph in ("B1", "B2", "B3"):
        frac = profile_brake_fraction(package, ph)
        if frac is not None:
            return frac
    if int(handle_notch) == NEUTRAL_NOTCH:
        return profile_brake_fraction(package, "neutral")
    for notch, label in SERVICE_HANDLES_WEAK_TO_STRONG:
        if int(notch) == int(handle_notch):
            return profile_brake_fraction(package, label)
    return profile_brake_fraction(package, "neutral")


def apply_vehicle_brake_actuator(
    cmd: BrakeCommand,
    package: Optional[dict[str, Any]],
) -> BrakeCommand:
    """
    Añade ``target_fraction`` en layout MC desde ``brake_input`` del paquete.

    El plan P1 sigue en fases B1–B3 / muesca lógica UK; el cable solo lleva 0..1 del perfil.
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
        frac = mc_fraction_for_plan_handle(
            package, phase="NEU", handle_notch=n
        )
        if frac is None:
            return cmd
        return replace(cmd, target_fraction=frac)
    if notch is None and not cmd.phase:
        return cmd
    n = int(notch) if notch is not None else NEUTRAL_NOTCH
    frac = mc_fraction_for_plan_handle(
        package, phase=cmd.phase or "", handle_notch=n
    )
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
    """Valor en línea ``PowerBrakeHandle`` (323: muesca/8; MC: ``brake_input`` del paquete)."""
    n = int(notch)
    if package and uses_mc_analog_ipc(package):
        frac = mc_fraction_for_plan_handle(
            package, phase="", handle_notch=n
        )
        if frac is not None:
            return frac
    return combined_notch_to_value(n)


def clear_package_cache() -> None:
    _load_all_packages.cache_clear()
