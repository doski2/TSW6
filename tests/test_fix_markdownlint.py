"""MD060 compact — extra space to the left of table pipes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "tools"))

from fix_markdownlint import (  # noqa: E402
    count_compact_extra_space_left,
    fix_tables,
    pick_md060_style,
    table_needs_md060_fix,
)

PADDED = """\
| Pieza         | TSW6 hoy | Dastsc | Qué estudiar en v2 |
| ------------- | -------- | ------ | ------------------ |
| Fuente `arr`  | bd | OCR | Nosotros |
| Holgura       | dist/v | Igual | tests |
"""

CFG_ANY = {"style": "any", "aligned_delimiter": False}


def test_md060_detects_extra_space_left_of_pipe():
    header = "| Pieza         | TSW6 hoy |"
    assert count_compact_extra_space_left([header]) == 1
    assert header[16] == "|"  # same pipe markdownlint flags at column 17


def test_md060_padded_table_needs_compact_fix():
    lines = PADDED.splitlines()
    assert table_needs_md060_fix(lines, CFG_ANY)
    assert pick_md060_style(lines, CFG_ANY) == "compact"


def test_md060_fix_removes_padding_before_pipe():
    fixed, n = fix_tables(PADDED, CFG_ANY)
    assert n >= 1
    assert "| Pieza | TSW6 hoy |" in fixed
    assert "Pieza         |" not in fixed
    assert count_compact_extra_space_left(fixed.splitlines()) == 0
