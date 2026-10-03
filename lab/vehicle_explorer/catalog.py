"""Inventario de sesiones ApiExplorer en lab_exports/exports/."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Archivos típicos por modo (PLAN_API_EXPLORER / ApiExplorerMod README)
EXPORT_FILES = (
    "session.json",
    "hud_batch.json",
    "controls.json",
    "driver_aid.json",
    "formation.json",
    "formation_http.json",
    "reflect_shallow.json",
    "correlate_tick.json",
)


@dataclass
class LabSession:
    session_id: str
    path: Path
    vehicle_class: Optional[str] = None
    captured_at: Optional[str] = None
    files_present: list[str] = field(default_factory=list)
    files_missing: list[str] = field(default_factory=list)

    @property
    def checklist_ok(self) -> bool:
        required = {"session.json", "controls.json", "hud_batch.json", "driver_aid.json"}
        return required.issubset(set(self.files_present))


def _read_session_meta(session_dir: Path) -> tuple[Optional[str], Optional[str]]:
    meta = session_dir / "session.json"
    if not meta.is_file():
        return None, None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, None
    vc = data.get("vehicle_class") or data.get("vehicle")
    ts = data.get("captured_at") or data.get("timestamp") or data.get("session_id")
    return (str(vc) if vc else None, str(ts) if ts else None)


def list_sessions(exports_dir: Path) -> list[LabSession]:
    if not exports_dir.is_dir():
        return []
    out: list[LabSession] = []
    for child in sorted(exports_dir.iterdir(), key=lambda p: p.name, reverse=True):
        if not child.is_dir():
            continue
        present = [name for name in EXPORT_FILES if (child / name).is_file()]
        missing = [name for name in EXPORT_FILES if name not in present]
        vc, ts = _read_session_meta(child)
        out.append(
            LabSession(
                session_id=child.name,
                path=child,
                vehicle_class=vc,
                captured_at=ts,
                files_present=present,
                files_missing=missing,
            )
        )
    return out


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_controls(controls_path: Path) -> list[str]:
    if not controls_path.is_file():
        return []
    data = load_json(controls_path)
    lines: list[str] = []
    hint = data.get("layout_hint")
    if hint:
        lines.append(f"layout_hint: {hint}")
    lua = data.get("lua")
    levers = data.get("levers") or data.get("controls")
    if levers is None and isinstance(lua, dict):
        levers = lua.get("levers")
    ipc_aliases = data.get("ipc_aliases")
    if isinstance(ipc_aliases, dict) and ipc_aliases:
        lines.append("ipc_aliases: " + ", ".join(f"{k}→{v}" for k, v in sorted(ipc_aliases.items())))
    if isinstance(levers, dict):
        for name, spec in sorted(levers.items()):
            notches = ""
            if isinstance(spec, dict) and spec.get("notches"):
                notches = f" ({len(spec['notches'])} notches)"
            lines.append(f"  • {name}{notches}")
    elif isinstance(levers, list):
        for item in levers:
            if isinstance(item, dict):
                name = item.get("name", item)
                notches = ""
                if item.get("notches"):
                    notches = f" ({len(item['notches'])} notches)"
                lines.append(f"  • {name}{notches}")
    return lines
