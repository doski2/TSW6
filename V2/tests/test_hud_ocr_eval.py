from __future__ import annotations

import _path  # noqa: F401

import pytest

from tsw6v2.hud_ocr_eval import evaluate, extract_captures, per_station_offset

MPH = 0.44704


def _session(*, app_bias_m: float, ocr_age_s: float = 0.4, noise: float = 0.0):
    """Tren a 40 mph acercándose desde 600 m; la app va ``app_bias_m`` de más; OCR cada 1 s."""
    ticks = []
    speed_ms = 40 * MPH
    true = 600.0
    t = 0.0
    last_ocr = -10.0
    age = None
    ocr_val = None
    i = 0
    while true > 60:
        if t - last_ocr >= 1.0:
            last_ocr = t
            ocr_val = true + speed_ms * ocr_age_s + (noise if i % 2 else -noise)
            age = ocr_age_s
        elif age is not None:
            age = ocr_age_s + (t - last_ocr)
        ticks.append(
            {
                "type": "tick",
                "t_ms": t * 1000,
                "spd_mph": 40.0,
                "station_name": "X",
                "stn_dist_m": true + app_bias_m,
                "hud_ocr_m": ocr_val,
                "hud_ocr_age_s": age,
            }
        )
        t += 0.05
        true -= speed_ms * 0.05
        i += 1
    return ticks


def test_extract_captures_counts_new_readings_only() -> None:
    segs = extract_captures(_session(app_bias_m=0.0))
    assert len(segs) == 1
    assert 25 <= len(segs[0]) <= 35  # ~1 por segundo durante ~30 s


def test_anchor_corrects_constant_app_bias() -> None:
    segs = extract_captures(_session(app_bias_m=100.0))
    rows = {(r["policy"], r["band"]): r for r in evaluate(segs, (1, 3))}
    app = rows[("app (actual)", "300-1000 m")]
    anchor = rows[("ancla cada 3", "300-1000 m")]
    assert app["mae"] == pytest.approx(100.0, abs=1.5)
    assert anchor["mae"] < 3.0  # odometría exacta entre anclas: el sesgo desaparece


def test_anchor_error_grows_with_noise_when_every_n_is_large() -> None:
    segs = extract_captures(_session(app_bias_m=0.0, noise=8.0))
    rows = {(r["policy"], r["band"]): r for r in evaluate(segs, (1, 10))}
    assert rows[("ancla cada 10", "300-1000 m")]["n"] > 0
    assert rows[("ancla cada 1", "300-1000 m")]["n"] == 0  # N=1 ancla siempre: no hay no-ancla


def test_per_station_offset_reports_median() -> None:
    segs = extract_captures(_session(app_bias_m=35.0))
    off = per_station_offset(segs)["X"]
    assert off["median_m"] == pytest.approx(35.0, abs=1.5)
