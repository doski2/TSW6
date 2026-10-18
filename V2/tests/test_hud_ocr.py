from __future__ import annotations

import _path  # noqa: F401

import pytest

from tsw6v2.hud_ocr import FT_TO_M, find_tesseract, parse_hud_distance, parse_region


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.465 ft (pies)", 1465 * FT_TO_M),
        ("1,465 ft", 1465 * FT_TO_M),
        ("51 ft (pies)", 51 * FT_TO_M),
        ("3.932 ft", 3932 * FT_TO_M),
        ("340 m", 340.0),
        ("0,9 mi", 0.9 * 1609.344),
        ("  7.759 FT (pies)\n", 7759 * FT_TO_M),
        ("1 465 ft", 1465 * FT_TO_M),
    ],
)
def test_parse_hud_distance_units_and_thousands(text: str, expected: float) -> None:
    assert parse_hud_distance(text) == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize("text", ["", "ft", "DETENGASE EN EL LUGAR", "0 ft", "999999 ft"])
def test_parse_hud_distance_rejects_garbage(text: str) -> None:
    assert parse_hud_distance(text) is None


def test_parse_region_validates_fractions() -> None:
    assert parse_region("0.1,0.2,0.3,0.05") == (0.1, 0.2, 0.3, 0.05)
    assert parse_region("2,0.2,0.3,0.05") != (2.0, 0.2, 0.3, 0.05)
    assert parse_region("basura") == parse_region("")


def test_ocr_reads_rendered_hud_text() -> None:
    """Prueba de extremo a extremo con texto dibujado; se omite sin Tesseract/Pillow/fuente."""
    pytest.importorskip("pytesseract")
    pytest.importorskip("PIL")
    tess = find_tesseract()
    if not tess:
        pytest.skip("Tesseract no instalado")
    from PIL import Image, ImageDraw, ImageFont
    import pytesseract

    from tsw6v2.hud_ocr import _OCR_CONFIG, _preprocess

    try:
        font = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        pytest.skip("fuente arial.ttf no disponible")
    img = Image.new("RGB", (260, 50), (25, 30, 38))
    ImageDraw.Draw(img).text((10, 8), "1.465 ft (pies)", fill=(235, 235, 235), font=font)
    pytesseract.pytesseract.tesseract_cmd = tess
    raw = pytesseract.image_to_string(_preprocess(img), config=_OCR_CONFIG)
    assert parse_hud_distance(raw) == pytest.approx(1465 * FT_TO_M, abs=0.5)
