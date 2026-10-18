"""Evaluación offline: ¿compensa corregir la distancia a la estación cada N capturas del HUD?

Lee el JSONL de una sesión grabada con ``--hud-ocr`` (campos ``hud_ocr_m`` y ``hud_ocr_age_s`` por
tick) y compara, en cada captura nueva del HUD, tres estimaciones de la distancia al marcador:

* **app**: ``stn_dist_m`` tal como la calculó el agente (HTTP + ``v×dt``);
* **ancla cada N**: se fija la distancia al valor del HUD en cada N-ésima captura y entre medias se
  resta lo recorrido (odometría de ``spd_mph``). Se evalúa en las capturas que NO son ancla.

Todo se pasa a «distancia ahora»: la lectura del HUD llega con ``hud_ocr_age_s`` de antigüedad y se
le resta ``v × edad``. Es solo medición; no interviene en el frenado.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

MPH_TO_MS = 0.44704
DISTANCE_BANDS = ((0.0, 100.0), (100.0, 300.0), (300.0, 1000.0))


@dataclass(frozen=True)
class Capture:
    """Una captura nueva del HUD alineada con un tick."""

    index: int
    t_s: float
    hud_now_m: float  # lectura del HUD llevada a «ahora»
    app_m: float
    odo_m: float  # metros recorridos acumulados en el segmento (odometría)
    speed_mph: float
    station: str


def load_ticks(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") == "tick":
                rows.append(row)
    return rows


def extract_captures(
    ticks: Iterable[dict[str, Any]],
    *,
    max_dist_m: float = 1000.0,
    min_speed_mph: float = 0.5,
) -> list[list[Capture]]:
    """Capturas nuevas agrupadas por aproximación (cambio de estación = otro segmento).

    Una captura es nueva cuando ``hud_ocr_age_s`` baja respecto al tick anterior (llegó otra).
    """
    segments: list[list[Capture]] = []
    current: list[Capture] = []
    station: Optional[str] = None
    odo = 0.0
    last_t: Optional[float] = None
    last_age: Optional[float] = None
    for i, row in enumerate(ticks):
        t_s = float(row.get("t_ms") or 0.0) / 1000.0
        spd = float(row.get("spd_mph") or 0.0)
        name = str(row.get("station_name") or "")
        if name != station:
            if len(current) >= 2:
                segments.append(current)
            current, station, odo, last_t, last_age = [], name, 0.0, None, None
        if last_t is not None and t_s > last_t:
            odo += spd * MPH_TO_MS * (t_s - last_t)
        last_t = t_s
        hud = row.get("hud_ocr_m")
        age = row.get("hud_ocr_age_s")
        if hud is None or age is None:
            last_age = None
            continue
        fresh = last_age is None or float(age) < last_age - 1e-6
        last_age = float(age)
        app = row.get("stn_dist_m")
        if not fresh or app is None or spd < min_speed_mph:
            continue
        hud_now = float(hud) - spd * MPH_TO_MS * float(age)
        if not 0.0 < hud_now <= max_dist_m:
            continue
        current.append(
            Capture(
                index=i,
                t_s=t_s,
                hud_now_m=hud_now,
                app_m=float(app),
                odo_m=odo,
                speed_mph=spd,
                station=name,
            )
        )
    if len(current) >= 2:
        segments.append(current)
    return segments


def _anchor_error(seg: list[Capture], every_n: int) -> list[tuple[float, float]]:
    """(distancia HUD, error firmado) de la estimación anclada en las capturas no-ancla."""
    out: list[tuple[float, float]] = []
    anchor: Optional[Capture] = None
    for k, cap in enumerate(seg):
        if k % every_n == 0:
            anchor = cap
            continue
        assert anchor is not None
        est = anchor.hud_now_m - (cap.odo_m - anchor.odo_m)
        out.append((cap.hud_now_m, est - cap.hud_now_m))
    return out


def _stats(errors: list[float]) -> dict[str, Optional[float]]:
    if not errors:
        return {"n": 0, "mae": None, "bias": None, "p95": None}
    absolute = sorted(abs(e) for e in errors)
    return {
        "n": len(errors),
        "mae": round(statistics.fmean(absolute), 1),
        "bias": round(statistics.fmean(errors), 1),
        "p95": round(absolute[min(len(absolute) - 1, int(0.95 * len(absolute)))], 1),
    }


def evaluate(
    segments: list[list[Capture]],
    every_n_options: Iterable[int] = (1, 2, 3, 5, 10),
) -> list[dict[str, Any]]:
    """Filas de resultados: política × banda de distancia."""
    rows: list[dict[str, Any]] = []
    for lo, hi in DISTANCE_BANDS:
        label = f"{int(lo)}-{int(hi)} m"
        app_err = [
            c.app_m - c.hud_now_m
            for seg in segments
            for c in seg
            if lo <= c.hud_now_m < hi
        ]
        rows.append({"policy": "app (actual)", "band": label, **_stats(app_err)})
        for n in every_n_options:
            errs = [
                e
                for seg in segments
                for d, e in _anchor_error(seg, max(1, int(n)))
                if lo <= d < hi
            ]
            rows.append({"policy": f"ancla cada {n}", "band": label, **_stats(errs)})
    return rows


def format_table(rows: list[dict[str, Any]]) -> str:
    header = f"{'política':<16}{'banda':<12}{'n':>6}{'|err| medio':>13}{'sesgo':>9}{'p95':>9}"
    lines = [header, "-" * len(header)]
    for r in rows:
        if r["n"] == 0:
            lines.append(f"{r['policy']:<16}{r['band']:<12}{0:>6}{'-':>13}{'-':>9}{'-':>9}")
            continue
        lines.append(
            f"{r['policy']:<16}{r['band']:<12}{r['n']:>6}"
            f"{r['mae']:>12.1f}m{r['bias']:>8.1f}m{r['p95']:>8.1f}m"
        )
    return "\n".join(lines)


def per_station_offset(segments: list[list[Capture]]) -> dict[str, dict[str, Optional[float]]]:
    """Desfase app − HUD por estación (mediana y dispersión), solo con el marcador a < 300 m."""
    by: dict[str, list[float]] = {}
    for seg in segments:
        for c in seg:
            if c.hud_now_m < 300.0:
                by.setdefault(c.station or "?", []).append(c.app_m - c.hud_now_m)
    out: dict[str, dict[str, Optional[float]]] = {}
    for name, vals in by.items():
        out[name] = {
            "n": float(len(vals)),
            "median_m": round(statistics.median(vals), 1),
            "stdev_m": round(statistics.pstdev(vals), 1) if len(vals) > 1 else None,
        }
    return out
