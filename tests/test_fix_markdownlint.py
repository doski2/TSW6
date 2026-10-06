"""MD060 — alineación de columnas (markdownlint table-column-style)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "tools"))

from fix_markdownlint import (  # noqa: E402
    count_aligned_violations,
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

# Válido en style aligned (contenido con padding interno; tuberías alineadas).
MD060_DOC_ALIGNED = """\
| Character | Meaning |
| --------- | ------- |
|     Y     |     Yes |
|     N     |      No |
"""

CFG_ANY = {"style": "any", "aligned_delimiter": False}
CFG_ALIGNED = {"style": "aligned", "aligned_delimiter": False}


def test_md060_detects_extra_space_left_of_pipe():
    header = "| Pieza         | TSW6 hoy |"
    assert count_compact_extra_space_left([header]) == 1
    assert header[16] == "|"


def test_md060_doc_example_valid_aligned():
    lines = MD060_DOC_ALIGNED.splitlines()
    assert count_aligned_violations(lines) == 0
    assert not table_needs_md060_fix(lines, CFG_ALIGNED)


def test_md060_padded_table_needs_fix():
    lines = PADDED.splitlines()
    assert table_needs_md060_fix(lines, CFG_ANY)
    assert pick_md060_style(lines, CFG_ANY) == "aligned"


def test_md060_fix_aligns_pipes():
    fixed, n = fix_tables(PADDED, CFG_ANY)
    assert n >= 1
    out_lines = fixed.splitlines()
    assert count_aligned_violations(out_lines) == 0
    assert "| Fuente `arr`  | bd       | OCR    | Nosotros           |" in fixed
    assert "Pieza         | TSW6" in fixed
