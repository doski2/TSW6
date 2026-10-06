"""Resolución de ``data/vehicles/<id>.json`` para modo IPC (323 muesca vs MC analog)."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
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
from tsw6v2.constants import B1_NOTCH, MC_INPUT_VALUE_EPS, NEUTRAL_NOTCH
from tsw6v2.target import SERVICE_HANDLES_WEAK_TO_STRONG, SERVICE_PHASE_BY_HANDLE

_PACKAGE_SCHEMA = "tsw6-vehicle-package/1"

# Etiquetas CLI/GUI por defecto (se sustituyen al detectar ``vehicle=`` en probe).
GENERIC_CLI_ROUTE_LABELS = frozenset({"", "cross-city", "gui", "session"})


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_vehicles_dir() -> Path:
    return repo_root() / "data" / "vehicles"


def vehicle_route_fleet(probe_vehicle: str) -> Optional[str]:
    """``uk`` | ``ny`` según prefijo GetData ``vehicle=`` (informe / HUD)."""
    u = (probe_vehicle or "").upper()
    if not u or u == "?":
        return None
    if "NYH" in u or "_MNR_" in u:
        return "ny"
    if "BCC" in u or "CLASS323" in u:
        return "uk"
    return None


def hud_route_fleet(route_name: str) -> Optional[str]:
    """Región aproximada del nombre de ruta HUD."""
    r = (route_name or "").lower()
    if not r:
        return None
    if "birmingham" in r or "cross-city" in r or "cross city" in r:
        return "uk"
    if (
        "harlem" in r
        or "hudson" in r
        or "new haven" in r
        or "grand central" in r
        or "mnr" in r
    ):
        return "ny"
    return None


def hud_route_matches_vehicle(detected_route: str, probe_vehicle: str) -> bool:
    """False si el HUD apunta a otra región que el tren (caché / match erróneo)."""
    vf = vehicle_route_fleet(probe_vehicle)
    df = hud_route_fleet(detected_route)
    if vf is None or df is None:
        return True
    return vf == df


def station_planning_trusted(
    probe_vehicle: str,
    hud_route_name: Optional[str],
) -> bool:
    """
    ¿Usar ``station_distance_m`` / bleed / FSM andén para este tren?

    Misma región UK/NY que ``resolve_session_route_name`` (``hud_route_matches_vehicle``).
    Sin ruta HUD conocida no se puede contrastar — se confía (``Planning.txt`` solo).
    """
    vehicle = (probe_vehicle or "").strip()
    if not vehicle or vehicle == "?":
        return True
    route = (hud_route_name or "").strip()
    if not route:
        return True
    return hud_route_matches_vehicle(route, vehicle)


@dataclass(frozen=True)
class SessionRouteMeta:
    """Metadatos de escenario en ``data/vehicles/*.json`` (informe + CLI)."""

    display: Optional[str]
    cli_slug: Optional[str]


def session_route_meta_for_probe(probe_vehicle: str) -> SessionRouteMeta:
    pkg = resolve_vehicle_package(probe_vehicle)
    if not pkg:
        return SessionRouteMeta(None, None)
    display = str(pkg.get("session_route") or "").strip() or None
    slug = str(pkg.get("session_route_cli") or "").strip() or None
    if not slug and uses_mc_analog_ipc(pkg):
        vid = str(pkg.get("vehicle_id") or "").strip()
        slug = vid.replace("_", "-") if vid else None
    return SessionRouteMeta(display, slug)


def session_route_hint_for_probe(probe_vehicle: str) -> Optional[str]:
    """Etiqueta legible para informes JSONL/HTML."""
    return session_route_meta_for_probe(probe_vehicle).display


def session_route_cli_slug_for_probe(probe_vehicle: str) -> Optional[str]:
    """Slug ``--route`` / campo ``route`` en metadatos de sesión."""
    return session_route_meta_for_probe(probe_vehicle).cli_slug


def is_generic_cli_route_label(route: str) -> bool:
    return (route or "").strip().lower() in GENERIC_CLI_ROUTE_LABELS


def resolve_session_route_name(
    *,
    vehicle: str,
    detected_route: Optional[str] = None,
    cli_route: Optional[str] = None,
) -> str:
    """
    Nombre de escenario para informe (sin servicio ni sufijo ``[cli=]``).

    Prioridad: ``session_route`` del paquete → HUD si cuadra con el tren → etiqueta CLI.
    """
    meta = session_route_meta_for_probe(vehicle) if vehicle else SessionRouteMeta(None, None)
    detected = detected_route
    if detected and vehicle and not hud_route_matches_vehicle(str(detected), vehicle):
        detected = None
    label = meta.display or detected
    if label:
        return label
    return str(cli_route or "?")


def vehicle_class_matches(probe_vehicle: str, package_class: str) -> bool:
    """
    Igualdad exacta, ``klass in probe`` (sufijo UE) o ``probe.startswith(klass)``.

    Prefijo corto en JSON (p. ej. ``RVM_NYH_MNR_M3a``) cubre coches A/B sin duplicar paquetes.
    """
    probe = (probe_vehicle or "").strip()
    klass = (package_class or "").strip()
    if not probe or not klass:
        return False
    if probe == klass:
        return True
    return klass in probe or probe.startswith(klass)


def station_platform_tail_m(package: Optional[dict[str, Any]]) -> float:
    """Metros de cola tras el marker para salida andén (0 = UK corto / sin dato)."""
    if not package:
        return 0.0
    station = package.get("station")
    if isinstance(station, dict):
        raw = station.get("platform_tail_m")
        if raw is not None:
            return float(raw)
    return 0.0


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


def mc_ipc_target_is_neutral_hold(
    package: Optional[dict[str, Any]],
    target_fraction: float,
) -> bool:
    """COAST/RELEASE a neutro: objetivo IPC en o por encima del neutro del paquete."""
    neu = profile_neutral_fraction(package)
    if neu is None:
        return False
    return float(target_fraction) >= float(neu) - MC_INPUT_VALUE_EPS


def mc_has_traction_above_neutral(snap: Any, package: Optional[dict[str, Any]]) -> bool:
    """Tracción MC para emitir COAST (HUD ``power`` o ``mc_input`` > neutro)."""
    if snap is None or not package or not uses_mc_analog_ipc(package):
        return False
    from tsw6v2.bridge.getdata import power_to_combined_notch

    power = getattr(snap, "power", None)
    power_neg = bool(getattr(snap, "power_neg", False))
    if power is not None and not power_neg and float(power) > 0.0:
        combined = power_to_combined_notch(power, power_neg)
        if combined is not None and combined > NEUTRAL_NOTCH:
            return True
    neu = profile_neutral_fraction(package)
    mc = getattr(snap, "mc_input", None)
    if neu is not None and mc is not None:
        return float(mc) > float(neu) + MC_INPUT_VALUE_EPS
    return False


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


_MC_PHASE_STRENGTH: dict[str, float] = {
    "B1": 1.0 / 3.0,
    "B2": 2.0 / 3.0,
    "B3": 1.0,
}
_MC_HANDLE_STRENGTH: dict[int, float] = {
    B1_NOTCH: 1.0 / 3.0,
    2: 2.0 / 3.0,
    1: 1.0,
}
def mc_service_brake_strength(handle_notch: int, phase: str) -> float:
    """Intensidad 0..1 entre neutro y B3 (fase P1 o muesca UK 3→2→1)."""
    ph = (phase or "").strip().upper()
    if ph in _MC_PHASE_STRENGTH:
        return _MC_PHASE_STRENGTH[ph]
    h = int(handle_notch)
    if h >= NEUTRAL_NOTCH:
        return 0.0
    return _MC_HANDLE_STRENGTH.get(h, 1.0)


def mc_service_brake_fraction(
    package: Optional[dict[str, Any]],
    *,
    handle_notch: int,
    phase: str = "",
) -> Optional[float]:
    """Interpola en eje MC entre ``neutral`` y ``B3`` según intensidad de servicio."""
    if not package or not uses_mc_analog_ipc(package):
        return None
    neu = profile_brake_fraction(package, "neutral")
    full = profile_brake_fraction(package, "B3")
    if neu is None or full is None:
        return None
    strength = mc_service_brake_strength(handle_notch, phase)
    if strength <= 0.0:
        return neu
    return master_controller_input_value(neu - strength * (neu - full))


def _read_snap_mc_input_d2(snap: Any) -> Optional[float]:
    """GetData ``mc_input`` normalizado (D2). Sin proxy HUD."""
    if snap is None:
        return None
    raw = getattr(snap, "mc_input", None)
    if raw is None:
        return None
    try:
        return master_controller_input_value(float(raw))
    except (TypeError, ValueError):
        return None


def probe_mc_input_fraction(
    snap: Any,
    package: Optional[dict[str, Any]],
) -> Optional[float]:
    """
    Posición MC para feedback IPC / rampa.

    Prioridad: ``mc_input`` (D2) → estimación ``lever_notch`` con mismo cable que P1.
    """
    if snap is None or not package or not uses_mc_analog_ipc(package):
        return None
    d2 = _read_snap_mc_input_d2(snap)
    if d2 is not None:
        return d2
    from tsw6v2.ipc import probe_lever

    neu = profile_brake_fraction(package, "neutral")
    if neu is None:
        return None
    lev = probe_lever(snap)
    if lev is None:
        return None
    if lev >= NEUTRAL_NOTCH:
        power = getattr(snap, "power", None)
        power_neg = bool(getattr(snap, "power_neg", False))
        if power is not None and not power_neg and float(power) > 0.05:
            return 1.0
        return neu
    return mc_fraction_for_plan_handle(
        package, phase="", handle_notch=int(lev)
    )


def _mc_feedback_fraction(
    snap: Any,
    package: dict[str, Any],
) -> Optional[float]:
    """Solo D2 — gates ``platform_bleed_release`` (sin estimación por palanca)."""
    return _read_snap_mc_input_d2(snap)


def mc_platform_bleed_neutral_ipc(
    snap: Any,
    package: Optional[dict[str, Any]],
) -> bool:
    """IPC/neutro MC alcanzado — no repetir ``platform_bleed_release`` (083123Z)."""
    if snap is None or not package or not uses_mc_analog_ipc(package):
        return False
    neutral = profile_brake_fraction(package, "neutral")
    if neutral is None:
        return False
    frac = _mc_feedback_fraction(snap, package)
    if frac is None:
        return False
    return float(frac) >= float(neutral) - MC_INPUT_VALUE_EPS


def mc_platform_bleed_b1_latched(
    snap: Any,
    package: Optional[dict[str, Any]],
) -> bool:
    """
    B1 mantenido antes de RELEASE a neutro en dwell MC.

    UK usa ``is_brake_applied``; MC solo con ``mc_input`` (sin proxy HUD).
    """
    if snap is None or not package or not uses_mc_analog_ipc(package):
        return False
    neutral = profile_brake_fraction(package, "neutral")
    b1 = profile_brake_fraction(package, "B1")
    if neutral is None or b1 is None:
        return False
    frac = _mc_feedback_fraction(snap, package)
    if frac is None:
        return False
    f = float(frac)
    n = float(neutral)
    b1f = float(b1)
    if f >= n - MC_INPUT_VALUE_EPS:
        return False
    tol = float(MC_INPUT_VALUE_EPS)
    # 110400Z: 0.55 entre B2 y B1 no es peldaño B1 (0.64); evitar wedge B2..B1+ε.
    return abs(f - b1f) <= tol


def mc_platform_bleed_suppress_reapply(
    snap: Any,
    package: Optional[dict[str, Any]],
) -> bool:
    """
    No repetir APPLY B1 en neutro o por encima del peldaño (ventilar / asentar).

    105359Z: ``mc_input`` 0.69 tras RELEASE no debe volver a B1 al instante.
    """
    if snap is None or not package or not uses_mc_analog_ipc(package):
        return False
    if mc_platform_bleed_neutral_ipc(snap, package):
        return True
    b1 = profile_brake_fraction(package, "B1")
    if b1 is None:
        return False
    frac = _mc_feedback_fraction(snap, package)
    if frac is None:
        return False
    return float(frac) > float(b1) + MC_INPUT_VALUE_EPS


def mc_platform_bleed_should_reapply_b1(
    snap: Any,
    package: Optional[dict[str, Any]],
) -> bool:
    """Episodio MC activo: ¿mandar otro APPLY B1 hacia el peldaño?"""
    if snap is None or not package or not uses_mc_analog_ipc(package):
        return False
    return not mc_platform_bleed_suppress_reapply(
        snap, package
    ) and not mc_platform_bleed_b1_latched(snap, package)


def _wire_fraction_from_brake_input(
    package: dict[str, Any],
    *,
    phase: str,
    handle_notch: int,
) -> Optional[float]:
    """IPC MC = peldaños ``brake_input`` del lab; interpolación solo si falta clave."""
    ph = (phase or "").strip().upper()
    if ph in _MC_PHASE_STRENGTH:
        wired = profile_brake_fraction(package, ph)
        if wired is not None:
            return wired
    h = int(handle_notch)
    if h < NEUTRAL_NOTCH:
        slot = SERVICE_PHASE_BY_HANDLE.get(h)
        if slot:
            wired = profile_brake_fraction(package, slot)
            if wired is not None:
                return wired
    return None


def mc_fraction_for_plan_handle(
    package: Optional[dict[str, Any]],
    *,
    phase: str,
    handle_notch: int,
) -> Optional[float]:
    """Plan P1 (fases B* / muesca lógica UK) → fracción ``brake_input`` en MC."""
    if not package or not uses_mc_analog_ipc(package):
        return None
    if int(handle_notch) == NEUTRAL_NOTCH and (phase or "").strip().upper() in (
        "",
        "NEU",
        "NEUTRAL",
    ):
        return profile_brake_fraction(package, "neutral")
    wired = _wire_fraction_from_brake_input(
        package, phase=phase, handle_notch=handle_notch
    )
    if wired is not None:
        return wired
    frac = mc_service_brake_fraction(
        package, handle_notch=int(handle_notch), phase=phase or ""
    )
    if frac is not None:
        return frac
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
    if cmd.kind not in ("APPLY", "RELEASE", "COAST_THROTTLE"):
        return cmd
    notch = cmd.target_notch
    if cmd.kind in ("RELEASE", "COAST_THROTTLE"):
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
