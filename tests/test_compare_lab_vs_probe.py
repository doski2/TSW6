"""Tests for compare_lab_vs_probe.py CLI."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "tools" / "compare_lab_vs_probe.py"
HUD = ROOT / "tests" / "fixtures" / "lab" / "hud_batch_323.json"
PROBE = ROOT / "tests" / "fixtures" / "lab" / "probe_line_323.txt"


def test_compare_lab_vs_probe_cli_ok() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(HUD), str(PROBE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok:" in proc.stdout
    assert "speed_ms:" in proc.stdout


def test_compare_lab_vs_probe_cli_json() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(HUD), str(PROBE), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mismatches"] == 0
    assert payload["session_id"] == "20260830T213100Z"
