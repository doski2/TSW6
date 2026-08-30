"""Tests for compare_lab_controls.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "tools" / "compare_lab_controls.py"


def test_compare_lab_controls_combined(tmp_path: Path) -> None:
    payload = {
        "vehicle_class": "RVM BCC WRM Class323 DMS A C",
        "layout_hint": "combined",
        "lua": {
            "levers": [
                {
                    "name": "PowerBrakeHandle",
                    "scope": "actor",
                    "class": "IrregularLeverComponent",
                    "read_value": 0.33,
                }
            ]
        },
        "ipc_aliases": {"PowerBrakeHandle": "PowerBrakeHandle"},
    }
    path = tmp_path / "controls.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "detect_control_layout: combined" in proc.stdout
    assert "layout_hint (Lua): combined" in proc.stdout
