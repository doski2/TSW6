"""``session_io``: un lector de JSONL de sesión con política de errores explícita."""

from __future__ import annotations

from pathlib import Path

import pytest

from tsw6v2.hud_ocr_eval import load_ticks as load_ticks_lenient
from tsw6v2.session_io import iter_session_rows
from tsw6v2.session_report import load_ticks as load_ticks_strict

_GOOD = '{"type": "session", "route": "r"}\n\n{"type": "tick", "seq": 1}\n{"type": "tick", "seq": 2}\n'


def _write(tmp_path: Path, text: str, raw: bytes | None = None) -> Path:
    p = tmp_path / "s.jsonl"
    if raw is not None:
        p.write_bytes(raw)
    else:
        p.write_text(text, encoding="utf-8")
    return p


def test_lee_filas_y_salta_lineas_en_blanco(tmp_path: Path) -> None:
    rows = list(iter_session_rows(_write(tmp_path, _GOOD), strict=True))
    assert [r["type"] for r in rows] == ["session", "tick", "tick"]


def test_estricto_falla_con_linea_rota(tmp_path: Path) -> None:
    p = _write(tmp_path, _GOOD + '{"type": "tick", "seq"\n')
    with pytest.raises(ValueError):
        list(iter_session_rows(p, strict=True))


def test_tolerante_ignora_linea_rota_y_bytes_no_utf8(tmp_path: Path) -> None:
    raw = _GOOD.encode() + b'{"type": "tick", "seq"\n' + b'\xff\xfe\n' + b'{"type": "tick", "seq": 3}\n'
    rows = list(iter_session_rows(_write(tmp_path, "", raw), strict=False))
    assert [r.get("seq") for r in rows if r["type"] == "tick"] == [1, 2, 3]


def test_load_ticks_de_los_dos_modulos_coinciden(tmp_path: Path) -> None:
    p = _write(tmp_path, _GOOD)
    session, strict_ticks = load_ticks_strict(p)
    lenient_ticks = load_ticks_lenient(p)
    assert session == {"type": "session", "route": "r"}
    assert [t["seq"] for t in strict_ticks] == [t["seq"] for t in lenient_ticks] == [1, 2]


def test_load_ticks_informe_falla_con_linea_rota_pero_el_analisis_no(tmp_path: Path) -> None:
    p = _write(tmp_path, _GOOD + "{roto\n")
    with pytest.raises(ValueError):
        load_ticks_strict(p)
    assert len(load_ticks_lenient(p)) == 2
