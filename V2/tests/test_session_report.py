from __future__ import annotations

import _path  # noqa: F401

import json
from pathlib import Path

from tsw6v2.session_report import (
    _kinematic_markers,
    finalize_session_report,
    session_ready_for_browser,
    session_ready_for_html,
    summarize,
    write_html_replay,
)


def test_finalize_session_report(tmp_path: Path) -> None:
    p = tmp_path / "s.jsonl"
    rows = [
        {"type": "session", "mode": "limit", "route": "test"},
        {
            "type": "tick",
            "tick": 1,
            "t_ms": 1000,
            "spd_mph": 55.0,
            "lever": 3,
            "lim_mph": 50.0,
            "lim_dist_m": 100.0,
            "eff_mph": 55.0,
            "p1": {
                "cmd": "APPLY",
                "phase": "B1",
                "dist_start_m": 5.0,
                "apply_now": True,
                "reason": "plan",
            },
            "ipc": {"sent": True},
        },
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    html = finalize_session_report(p, force=True)
    assert html is not None
    assert html.exists()
    assert "Replay P1" in html.read_text(encoding="utf-8")
    data = summarize(p)
    assert data["apply_ticks"] == 1


def test_html_shows_ds_zero_and_apply_zone(tmp_path: Path) -> None:
    p = tmp_path / "cross.jsonl"
    rows = [
        {"type": "session", "mode": "limit", "route": "test"},
        {
            "type": "tick",
            "tick": 1,
            "t_ms": 0,
            "spd_mph": 60.0,
            "lever": 6,
            "lim_mph": 55.0,
            "lim_dist_m": 500.0,
            "eff_mph": 60.0,
            "p1": {
                "cmd": None,
                "phase": "B1",
                "dist_start_m": 40.0,
                "apply_now": False,
                "reason": "command_none",
            },
        },
        {
            "type": "tick",
            "tick": 2,
            "t_ms": 1000,
            "spd_mph": 59.0,
            "lever": 6,
            "lim_mph": 55.0,
            "lim_dist_m": 460.0,
            "eff_mph": 60.0,
            "p1": {
                "cmd": "APPLY",
                "phase": "B1",
                "dist_start_m": -5.0,
                "apply_now": True,
                "reason": "plan",
            },
            "ipc": {"sent": True},
        },
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    markers = _kinematic_markers(
        [r for r in (json.loads(l) for l in p.read_text().splitlines()) if r.get("type") == "tick"]
    )
    assert len(markers) == 1
    assert markers[0]["t"] == 0.89
    assert markers[0]["lim_dist_m"] == 464.4
    html = tmp_path / "out.html"
    write_html_replay(p, html)
    text = html.read_text(encoding="utf-8")
    assert "ds=0" in text or "Margen cinemático" in text
    assert "464 m</td>" in text
    assert "Marcas cinemáticas" in text
    assert '<path d="' in text


def test_html_shows_fb_and_pressure(tmp_path: Path) -> None:
    p = tmp_path / "fb.jsonl"
    rows = [
        {"type": "session", "mode": "limit", "route": "test"},
        {
            "type": "tick",
            "tick": 1,
            "t_ms": 1000,
            "spd_mph": 55.0,
            "lever": 3,
            "brake_cyl_bar": 2.8,
            "lim_mph": 50.0,
            "lim_dist_m": 80.0,
            "eff_mph": 55.0,
            "p1": {
                "cmd": "APPLY",
                "phase": "B1",
                "dist_start_m": 5.0,
                "apply_now": True,
                "reason": "plan",
            },
            "fb": {
                "a_pred_ms2": 0.5,
                "a_obs_ms2": 0.2,
                "shortfall": True,
            },
            "ipc": {"sent": True},
        },
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    data = summarize(p)
    assert data["fb_ticks"] == 1
    assert data["fb_shortfall"] == 1
    html = tmp_path / "fb.html"
    write_html_replay(p, html)
    text = html.read_text(encoding="utf-8")
    assert "Feedback decel" in text
    assert "Presión cilindro" in text
    assert "FB shortfall" in text


def test_finalize_skips_short_session(tmp_path: Path) -> None:
    p = tmp_path / "short.jsonl"
    rows = [
        {"type": "session", "mode": "limit", "route": "test"},
        {"type": "tick", "tick": 1, "t_ms": 100, "spd_mph": 50.0, "lever": 4},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    data = summarize(p)
    assert not session_ready_for_html(data)
    assert finalize_session_report(p, summary=data) is None


def test_session_ready_for_browser_thresholds() -> None:
    html_ok = {"n_ticks": 20, "duration_s": 8.0}
    assert session_ready_for_html(html_ok)
    assert not session_ready_for_browser(html_ok)

    browser_ok = {"n_ticks": 50, "duration_s": 15.0}
    assert session_ready_for_html(browser_ok)
    assert session_ready_for_browser(browser_ok)

    short = {"n_ticks": 5, "duration_s": 3.0}
    assert not session_ready_for_html(short)
    assert not session_ready_for_browser(short)


def test_html_shows_station_panel(tmp_path: Path) -> None:
    p = tmp_path / "station.jsonl"
    rows = [
        {"type": "session", "mode": "station", "route": "cross-city"},
        {
            "type": "tick",
            "tick": 1,
            "t_ms": 0,
            "spd_mph": 55.0,
            "lever": 5,
            "lim_mph": 55.0,
            "lim_dist_m": 400.0,
            "stn_dist_m": 800.0,
            "eff_mph": 60.0,
            "p1_tgt": "SPEED_LIMIT",
            "p1": {"reason": "no_plan", "layer": "OK"},
        },
        {
            "type": "tick",
            "tick": 2,
            "t_ms": 1000,
            "spd_mph": 52.0,
            "lever": 4,
            "lim_mph": 55.0,
            "lim_dist_m": 350.0,
            "stn_dist_m": 420.0,
            "eff_mph": 55.0,
            "p1_tgt": "STATION",
            "stn_fsm": "APPROACHING",
            "p1": {
                "cmd": "APPLY",
                "phase": "B2",
                "dist_start_m": 50.0,
                "apply_now": True,
                "reason": "emergency",
                "detail": "P1-EMERGENCIA-STATION",
            },
            "ipc": {"sent": True},
        },
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    data = summarize(p)
    assert data["station_ticks"] == 2
    assert data["p1_tgt_station_ticks"] == 1
    html = tmp_path / "stn.html"
    write_html_replay(p, html)
    text = html.read_text(encoding="utf-8")
    assert "cartel + andén" in text
    assert "Distancia al andén" in text
    assert "Andén (estación)" in text
    assert "objetivo STATION" in text


def test_station_event_rows_dedup_apply(tmp_path: Path) -> None:
    from tsw6v2.session_report import _station_event_rows

    ticks = [
        {
            "tick": i,
            "t_ms": i * 1000,
            "stn_dist_m": 100.0,
            "p1_tgt": "STATION",
            "p1": {"cmd": "APPLY", "reason": "emergency"},
        }
        for i in range(1, 6)
    ]
    rows = _station_event_rows(ticks)
    apply_rows = [r for r in rows if r["event"] == "APPLY andén"]
    assert len(apply_rows) == 1


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
