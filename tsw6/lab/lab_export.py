"""Load ApiExplorer JSON exports and mirror mods/ApiExplorerMod/Scripts/serialize.lua."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

from tsw6.telemetry.tsw_ue4ss_reader import parse_probe_line, power_to_combined_notch

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_LAB = ROOT / "tests" / "fixtures" / "lab"
REF_SESSION_ID = "20260830T213100Z"

MatchKind = Literal["exact", "fuzzy", "mismatch", "skipped", "missing_lab", "missing_probe"]


def fixture_session_dir(session_id: str = REF_SESSION_ID) -> Path:
    return FIXTURES_LAB / session_id


def load_lab_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def load_hud_batch(path: Path) -> dict[str, Any]:
    data = load_lab_json(path)
    if data.get("mode") != "hud_batch":
        raise ValueError(f"not a hud_batch export: {path}")
    return data


def _escape_str(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def encode_lua_value(value: Any, stack: Optional[set[int]] = None) -> str:
    """Encode a Python value using the same rules as serialize.lua."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return "null"
        return format(value, ".10g")
    if isinstance(value, str):
        return f'"{_escape_str(value)}"'

    if not isinstance(value, (dict, list)):
        return "null"

    stack = stack or set()
    obj_id = id(value)
    if obj_id in stack:
        return '"<cycle>"'
    stack.add(obj_id)

    try:
        if isinstance(value, list):
            parts = [encode_lua_value(item, stack) for item in value]
            return "[" + ",".join(parts) + "]"

        if isinstance(value, dict):
            keys = sorted(value.keys(), key=lambda k: str(k))
            if not keys:
                return "{}"
            is_array = all(isinstance(k, int) for k in keys)
            if is_array and keys == list(range(1, len(keys) + 1)):
                parts = [encode_lua_value(value[i], stack) for i in range(1, len(keys) + 1)]
                return "[" + ",".join(parts) + "]"
            parts = [
                encode_lua_value(str(k), stack) + ":" + encode_lua_value(value[k], stack)
                for k in keys
            ]
            return "{" + ",".join(parts) + "}"
    finally:
        stack.discard(obj_id)

    return "null"


def encode_lua_json(value: Any) -> str:
    return encode_lua_value(value)


def _lua_scalar(lua: dict[str, Any], method: str, field: str) -> Any:
    block = lua.get(method)
    if not isinstance(block, dict):
        return None
    return block.get(field)


def derive_probe_fields_from_hud(hud_batch: dict[str, Any]) -> dict[str, Any]:
    """Map hud_batch.lua HUD_Get* blocks to GetData-style scalar fields."""
    lua = hud_batch.get("lua") or {}
    if not isinstance(lua, dict):
        return {}

    power_block = lua.get("HUD_GetPowerHandle")
    power: Optional[float] = None
    power_neg = False
    if isinstance(power_block, dict):
        raw_power = power_block.get("power")
        if isinstance(raw_power, (int, float)):
            power = float(raw_power)
        if "is_negative" in power_block:
            power_neg = bool(power_block.get("is_negative"))
        elif power is not None:
            power_neg = False

    speed_ms = _lua_scalar(lua, "HUD_GetSpeed", "Speed (ms)")
    accel_ms2 = _lua_scalar(lua, "HUD_GetAcceleration", "Acceleration (ms2)")
    train_brake = _lua_scalar(lua, "HUD_GetTrainBrakeHandle", "HandlePosition")
    loco_brake = _lua_scalar(lua, "HUD_GetLocomotiveBrakeHandle", "HandlePosition")
    dyn_brake = _lua_scalar(lua, "HUD_GetElectricBrakeHandle", "HandlePosition")
    max_speed_ms = _lua_scalar(lua, "HUD_GetMaxPermittedSpeed", "max_speed")

    brake_cyl_bar: Optional[float] = None
    gauge = lua.get("HUD_GetBrakeGauge_1")
    if isinstance(gauge, dict):
        pa = gauge.get("RedNeedle (Pa)")
        if isinstance(pa, (int, float)):
            brake_cyl_bar = float(pa) / 100_000.0

    handle_notch = (
        power_to_combined_notch(power, power_neg) if power is not None else None
    )

    out: dict[str, Any] = {}
    if speed_ms is not None:
        out["speed_ms"] = float(speed_ms)
    if power is not None:
        out["power"] = float(power)
        out["power_neg"] = power_neg
    if handle_notch is not None:
        out["handle_notch"] = handle_notch
    if train_brake is not None:
        out["train_brake"] = float(train_brake)
    if loco_brake is not None:
        out["loco_brake"] = float(loco_brake)
    if dyn_brake is not None:
        out["dyn_brake"] = float(dyn_brake)
    if accel_ms2 is not None:
        out["accel_ms2"] = float(accel_ms2)
    if brake_cyl_bar is not None:
        out["brake_cyl_bar"] = brake_cyl_bar
    if max_speed_ms is not None:
        out["max_speed_ms"] = float(max_speed_ms)
    return out


def extract_amps_snapshot(hud_batch: dict[str, Any]) -> dict[str, Any]:
    """Scalars for L0.6f ammeter study from one hud_batch export."""
    lua = hud_batch.get("lua") or {}
    if not isinstance(lua, dict):
        lua = {}

    amps_raw = _lua_scalar(lua, "HUD_GetAmmeter", "Amps")
    amps: Optional[float] = float(amps_raw) if isinstance(amps_raw, (int, float)) else None

    tractive_block = lua.get("HUD_GetTractiveEffort")
    tractive_effort_n: Optional[float] = None
    brake_effort_n: Optional[float] = None
    if isinstance(tractive_block, dict):
        te = tractive_block.get("TractiveEffort (N)")
        be = tractive_block.get("BrakeEffort (N)")
        if isinstance(te, (int, float)):
            tractive_effort_n = float(te)
        if isinstance(be, (int, float)):
            brake_effort_n = float(be)

    is_slipping = _lua_scalar(lua, "HUD_GetIsSlipping", "IsSlipping")

    out = derive_probe_fields_from_hud(hud_batch)
    out["amps"] = amps
    out["tractive_effort_n"] = tractive_effort_n
    out["brake_effort_n"] = brake_effort_n
    if is_slipping is not None:
        out["is_slipping"] = bool(is_slipping)
    return out


AMPS_CAPTURE_STEPS: list[tuple[str, str]] = [
    ("reposo", "Parado, release, power 0"),
    ("traccion_p4", "~30 mph, P3–P4 sostenido"),
    ("retencion", "Retención / regen (power neg)"),
    ("dyn_brake", "Solo freno eléctrico (dyn_brake, sin B aire)"),
    ("freno_b2", "Freno aire B2–B3 sin power"),
]


def list_hud_batch_exports(session_dir: Path) -> list[Path]:
    """hud_batch.json plus hud_batch_<label>.json copies in a session folder."""
    paths: list[Path] = []
    main = session_dir / "hud_batch.json"
    if main.is_file():
        paths.append(main)
    paths.extend(sorted(session_dir.glob("hud_batch_*.json")))
    return paths


def summarize_amps_session(session_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in list_hud_batch_exports(session_dir):
        hud = load_hud_batch(path)
        snap = extract_amps_snapshot(hud)
        snap["file"] = path.name
        snap["session_id"] = str(hud.get("session_id") or session_dir.name)
        snap["captured_at"] = hud.get("captured_at")
        snap["vehicle_class"] = hud.get("vehicle_class")
        rows.append(snap)
    return rows


def amps_session_verdict(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "no_captures"
    amps_values = [r["amps"] for r in rows if r.get("amps") is not None]
    if not amps_values:
        return "no_amps_field"
    if all(abs(float(a)) < 1e-9 for a in amps_values):
        return "always_zero"
    return "variable"


def compare_values(expected: Any, actual: Any, rel_tol: float = 1e-5, abs_tol: float = 1e-4) -> MatchKind:
    if expected is None and actual is None:
        return "exact"
    if expected is None or actual is None:
        return "mismatch"
    if isinstance(expected, bool) or isinstance(actual, bool):
        return "exact" if bool(expected) == bool(actual) else "mismatch"
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        e, a = float(expected), float(actual)
        if e == a:
            return "exact"
        if math.isclose(e, a, rel_tol=rel_tol, abs_tol=abs_tol):
            return "fuzzy"
        return "mismatch"
    return "exact" if expected == actual else "mismatch"


@dataclass
class ProbeCompareRow:
    field: str
    lab_value: Any
    probe_value: Any
    match: MatchKind
    note: str = ""


PROBE_COMPARE_FIELDS = (
    "speed_ms",
    "power",
    "power_neg",
    "handle_notch",
    "train_brake",
    "loco_brake",
    "dyn_brake",
    "accel_ms2",
    "brake_cyl_bar",
    "max_speed_ms",
)


def compare_hud_to_probe(
    hud_batch: dict[str, Any],
    probe_line: str,
    *,
    rel_tol: float = 1e-5,
    abs_tol: float = 1e-4,
) -> list[ProbeCompareRow]:
    lab = derive_probe_fields_from_hud(hud_batch)
    probe = parse_probe_line(probe_line)
    rows: list[ProbeCompareRow] = []

    for field in PROBE_COMPARE_FIELDS:
        lab_val = lab.get(field)
        probe_val = probe.get(field)
        if lab_val is None and probe_val is None:
            rows.append(
                ProbeCompareRow(field, lab_val, probe_val, "skipped", "both missing")
            )
            continue
        if lab_val is None:
            rows.append(
                ProbeCompareRow(field, lab_val, probe_val, "missing_lab", "not in hud_batch")
            )
            continue
        if probe_val is None:
            rows.append(
                ProbeCompareRow(
                    field, lab_val, probe_val, "missing_probe", "not in GetData line"
                )
            )
            continue
        tol_abs = abs_tol
        if field == "brake_cyl_bar":
            tol_abs = 0.05
        match = compare_values(lab_val, probe_val, rel_tol=rel_tol, abs_tol=tol_abs)
        note = ""
        if field == "brake_cyl_bar":
            note = "lab=HUD gauge Pa/1e5; probe=Simulation (may differ)"
        rows.append(ProbeCompareRow(field, lab_val, probe_val, match, note))
    return rows
