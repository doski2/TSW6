"""Tests for compare_v2_sessions.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "tools" / "compare_v2_sessions.py"
A = ROOT / "logs" / "v2" / "20260903T185740Z_cross-city_limit.jsonl"
B = ROOT / "logs" / "v2" / "20260903T222538Z_cross-city_limit.jsonl"


def test_compare_v2_sessions_cli() -> None:
    if not A.is_file() or not B.is_file():
        return
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(A), str(B)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Comparar sesiones" in proc.stdout
    assert "Primer APPLY" in proc.stdout
