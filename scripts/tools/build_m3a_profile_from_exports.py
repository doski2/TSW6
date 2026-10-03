#!/usr/bin/env python3
"""One-shot: merge lab controls + RailBridge dumps into data/vehicles/m3a_mnr.json."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tools.vehicles_json_from_lab import (  # noqa: E402
    _lever_entry,
    build_vehicle_package,
    write_vehicle_package,
)

LAB = ROOT / "data/lab_exports/exports/20261003T144934Z/controls.json"
RB_ACTOR = Path(
    r"c:/Users/doski/AppData/Local/RailBridge/cache/api-dumps/"
    "tsw-api-export-CurrentDrivableActor-20261003T152838Z.json"
)
RB_PLAYER = Path(
    r"c:/Users/doski/AppData/Local/RailBridge/cache/api-dumps/"
    "tsw-api-export-Player-20261003T152818Z.json"
)
RB_FORMATION = Path(
    r"c:/Users/doski/AppData/Local/RailBridge/cache/api-dumps/"
    "tsw-api-export-CurrentFormation-20261003T153131Z.json"
)
RB_DRIVER_INPUT = Path(
    r"c:/Users/doski/AppData/Local/RailBridge/cache/api-dumps/"
    "tsw-api-export-DriverInput-20261003T154503Z.json"
)
FORMATION_LEAD_INDEX = 0
OUT = ROOT / "data/vehicles/m3a_mnr.json"


def endpoint_value(tree: dict[str, Any], suffix: str) -> Any:
    """Last endpoint whose full_path ends with suffix."""
    found: Any = None

    def walk(node: dict[str, Any]) -> None:
        nonlocal found
        for e in node.get("endpoints") or []:
            fp = str(e.get("full_path") or "")
            if fp.endswith(suffix) or fp == suffix:
                found = e.get("value")
        for ch in node.get("children") or []:
            walk(ch)

    walk(tree)
    return found


def master_controller_from_actor(data: dict[str, Any], actor_ue_path: str) -> dict[str, Any]:
    tree = data.get("tree") or {}
    input_val = endpoint_value(tree, "MasterController.InputValue")
    obj_class = endpoint_value(tree, "MasterController.ObjectClass")
    if input_val is None:
        raise ValueError("MasterController.InputValue not found in CurrentDrivableActor dump")

    # Notches: search raw JSON for MasterController.Notches array (if crawled as property)
    raw = RB_ACTOR.read_text(encoding="utf-8")
    notches: list[dict[str, Any]] = []
    number_of_notches: Optional[int] = None
    current_notch_id: Optional[int] = None

    # Pattern: Property.NumberOfNotches near MasterController block in file
    m_n = re.search(
        r"CurrentDrivableActor/MasterController\.Property\.NumberOfNotches.*?\"value\":\s*(\d+)",
        raw,
        re.DOTALL,
    )
    if m_n:
        number_of_notches = int(m_n.group(1))

    # Extract list of {MinimumInputValue, MaximumInputValue, index} after MasterController
    mc_pos = raw.find("CurrentDrivableActor/MasterController")
    if mc_pos >= 0:
        sub = raw[mc_pos : mc_pos + 120_000]
        for block in re.finditer(
            r'"MinimumInputValue":\s*([-0-9.eE+]+),\s*"MaximumInputValue":\s*([-0-9.eE+]+)',
            sub,
        ):
            # Heuristic: only first contiguous run (MasterController notches)
            notches.append(
                {
                    "index": len(notches) + 1,
                    "MinimumInputValue": float(block.group(1)),
                    "MaximumInputValue": float(block.group(2)),
                }
            )
        # Stop if we hit another component's notches (Reverser values are 0, 0.33, 0.66)
        if len(notches) > 20:
            notches = []

    ue_path = ""
    if actor_ue_path:
        space = actor_ue_path.find(" ")
        if space > 0:
            ue_path = (
                f"IrregularLeverComponent {actor_ue_path[space + 1:]}.MasterController"
            )
    if not ue_path:
        ue_path = "IrregularLeverComponent (see lab lua.actor_ue_path).MasterController"

    entry: dict[str, Any] = {
        "ue_name": "MasterController",
        "component_class": str(obj_class or "IrregularLeverComponent"),
        "scope": "actor",
        "read_kind": "scalar",
        "read_value_at_capture": float(input_val),
        "ue_path": ue_path,
        "http_patch": "CurrentDrivableActor/MasterController.InputValue",
    }
    if number_of_notches is not None:
        entry["number_of_notches"] = number_of_notches
    if notches:
        entry["notches"] = notches
    else:
        entry["notches_pending"] = (
            "ApiExplorer F6 on drivable actor (lua Notches); HTTP crawl omits MC notch table"
        )
    return entry


def driver_input_meta(data: dict[str, Any]) -> dict[str, Any]:
    tree = data.get("tree") or {}
    children = tree.get("children") or []
    names = [str(c.get("node_name") or "") for c in children if c.get("node_name")]
    return {
        "captured_at_utc": data.get("captured_at_utc"),
        "control_count": len(names),
        "control_names": names,
        "input_values_at_capture": {
            "MasterController": endpoint_value(tree, "MasterController.InputValue"),
            "Reverser": endpoint_value(tree, "Reverser.InputValue"),
            "MasterKey": endpoint_value(tree, "MasterKey.InputValue"),
        },
        "master_key_number_of_notches": endpoint_value(
            tree, "MasterKey.Property.NumberOfNotches"
        ),
    }


def apply_driver_input_http_paths(package: dict[str, Any]) -> None:
    for name in ("MasterController", "Reverser", "MasterKey"):
        ctrl = package.get("controls", {}).get(name)
        if isinstance(ctrl, dict):
            ctrl["http_patch_driver_input"] = f"DriverInput/{name}.InputValue"


def formation_lead_meta(data: dict[str, Any]) -> dict[str, Any]:
    """Lead car (cab) from CurrentFormation/N — matches lab http_guess CurrentFormation/0/…"""
    tree = data.get("tree") or {}
    lead = FORMATION_LEAD_INDEX
    prefix = f"CurrentFormation/{lead}/"
    car_count = 0
    while endpoint_value(tree, f"CurrentFormation/{car_count}/ObjectName") is not None:
        car_count += 1
    return {
        "captured_at_utc": data.get("captured_at_utc"),
        "lead_index": lead,
        "car_count": car_count,
        "object_class": endpoint_value(tree, f"{prefix}ObjectClass"),
        "object_name": endpoint_value(tree, f"{prefix}ObjectName"),
        "input_values_at_capture": {
            "MasterController": endpoint_value(tree, f"{prefix}MasterController.InputValue"),
            "Reverser": endpoint_value(tree, f"{prefix}Reverser.InputValue"),
            "MasterKey": endpoint_value(tree, f"{prefix}MasterKey.InputValue"),
        },
    }


def apply_formation_http_paths(package: dict[str, Any]) -> None:
    lead = FORMATION_LEAD_INDEX
    for name in ("MasterController", "Reverser", "MasterKey"):
        ctrl = package.get("controls", {}).get(name)
        if isinstance(ctrl, dict):
            ctrl["http_patch_formation"] = f"CurrentFormation/{lead}/{name}.InputValue"


def player_context(data: dict[str, Any]) -> dict[str, Any]:
    tree = data.get("tree") or {}
    loc = endpoint_value(tree, "TransformComponent0.Property.RelativeLocation")
    rot = endpoint_value(tree, "TransformComponent0.Property.RelativeRotation")
    out: dict[str, Any] = {
        "captured_at_utc": data.get("captured_at_utc"),
        "relative_location": loc,
        "relative_rotation": rot,
    }
    return out


def main() -> int:
    controls = json.loads(LAB.read_text(encoding="utf-8"))
    package = build_vehicle_package(controls, vehicle_id="m3a_mnr", source_path=LAB)
    package["layout"] = "master_controller"

    actor_path = str(controls.get("lua", {}).get("actor_ue_path") or "")
    rb_actor = json.loads(RB_ACTOR.read_text(encoding="utf-8"))
    rb_player = json.loads(RB_PLAYER.read_text(encoding="utf-8"))

    package["controls"]["MasterController"] = master_controller_from_actor(rb_actor, actor_path)

    package["ipc_aliases"] = {
        "PowerBrakeHandle": "MasterController",
        "combined_brake": "MasterController",
    }
    package["master_controller"] = {
        "primary_lever": "MasterController",
        "http_primary": "CurrentDrivableActor/MasterController.InputValue",
        "http_formation_lead": (
            f"CurrentFormation/{FORMATION_LEAD_INDEX}/MasterController.InputValue"
        ),
        "http_driver_input": "DriverInput/MasterController.InputValue",
        "formation_lead_index": FORMATION_LEAD_INDEX,
    }

    rb_formation = None
    if RB_FORMATION.is_file():
        rb_formation = json.loads(RB_FORMATION.read_text(encoding="utf-8"))
        apply_formation_http_paths(package)

    rb_driver_input = None
    if RB_DRIVER_INPUT.is_file():
        rb_driver_input = json.loads(RB_DRIVER_INPUT.read_text(encoding="utf-8"))
        apply_driver_input_http_paths(package)

    hud_path = LAB.parent / "hud_batch.json"
    hud_at_capture: dict[str, Any] = {}
    if hud_path.is_file():
        hud = json.loads(hud_path.read_text(encoding="utf-8"))
        lua = hud.get("lua") or {}
        for key in (
            "HUD_GetPowerHandle",
            "HUD_GetTrainBrakeHandle",
            "HUD_GetElectricBrakeHandle",
            "HUD_GetIsTractionLocked",
        ):
            if key in lua:
                hud_at_capture[key] = lua[key]

    rb_block: dict[str, Any] = {
        "current_drivable_actor": str(RB_ACTOR).replace("\\", "/"),
        "captured_at_utc": rb_actor.get("captured_at_utc"),
        "player": {
            "path": str(RB_PLAYER).replace("\\", "/"),
            **player_context(rb_player),
        },
    }
    if rb_formation is not None:
        rb_block["current_formation"] = {
            "path": str(RB_FORMATION).replace("\\", "/"),
            **formation_lead_meta(rb_formation),
        }
    if rb_driver_input is not None:
        rb_block["driver_input"] = {
            "path": str(RB_DRIVER_INPUT).replace("\\", "/"),
            **driver_input_meta(rb_driver_input),
        }
    package["source"]["railbridge"] = rb_block
    if hud_at_capture:
        package["source"]["hud_at_capture"] = hud_at_capture
    package["source"]["profile_notes"] = (
        "DriverInput export confirms HTTP names; MasterController notches[] still need "
        "ApiExplorer F6 (lua reads UObject Notches — not exposed in HTTP crawl)."
    )

    if "combined" in package:
        del package["combined"]

    write_vehicle_package(package, OUT)
    print(f"Wrote {OUT}")
    print(
        f"controls={list(package['controls'].keys())} "
        f"mc_notches={len(package['controls']['MasterController'].get('notches') or [])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
