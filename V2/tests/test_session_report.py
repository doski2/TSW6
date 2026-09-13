from __future__ import annotations

import _path  # noqa: F401

import json
from pathlib import Path

from tsw6v2.session_report import (
    _kinematic_markers,
    enrich_ticks_active_time,
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


def test_html_signal_section(tmp_path: Path) -> None:
    p = tmp_path / "sig.jsonl"
    rows = [
        {"type": "session", "mode": "station", "route": "test"},
        {
            "type": "tick",
            "tick": 1,
            "t_ms": 0,
            "spd_mph": 15.0,
            "signal_red": True,
            "signal_dist_m": 120.0,
            "p1": {"reason": "no_plan"},
        },
        {
            "type": "tick",
            "tick": 2,
            "t_ms": 1000,
            "spd_mph": 14.0,
            "signal_red": False,
            "signal_dist_m": None,
            "p1": {"reason": "no_plan"},
        },
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = tmp_path / "out.html"
    write_html_replay(p, out)
    text = out.read_text(encoding="utf-8")
    assert "Señal (rojo)" in text
    assert "señal ROJO" in text
    data = summarize(p)
    assert data["signal_red_ticks"] == 1
    assert len(data["signal_events"]) >= 1


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


def test_html_shows_learn_events(tmp_path: Path) -> None:
    p = tmp_path / "learn.jsonl"
    rows = [
        {"type": "session", "mode": "limit", "route": "test"},
        {
            "type": "tick",
            "tick": 1,
            "t_ms": 1000,
            "spd_mph": 55.0,
            "lever": 3,
            "brake_cyl_bar": 2.8,
            "brake_fill_s": 2.5,
            "brake_fill_n": 1,
            "decel_observe_n": 0,
            "learn_kind": "fill",
            "learn_accepted": True,
            "learn_reject_reason": "accepted",
            "p1": {"cmd": "APPLY", "phase": "B1", "reason": "plan"},
        },
        {
            "type": "tick",
            "tick": 2,
            "t_ms": 3200,
            "spd_mph": 52.0,
            "lever": 3,
            "brake_cyl_bar": 2.9,
            "brake_fill_s": 2.5,
            "brake_fill_n": 1,
            "decel_observe_n": 0,
            "learn_kind": "decel",
            "learn_accepted": False,
            "learn_reject_reason": "decel_outlier",
            "p1": {"cmd": "APPLY", "phase": "B1", "reason": "plan"},
        },
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    data = summarize(p)
    assert data["learn_events"] == 2
    assert data["learn_accepted"] == 1
    assert data["learn_reject_reasons"].get("decel_outlier") == 1
    assert len(data["learn_rows"]) == 2
    html = tmp_path / "learn.html"
    write_html_replay(p, html)
    text = html.read_text(encoding="utf-8")
    assert "Aprendizaje (learner)" in text
    assert "Learn OK" in text
    assert "decel_outlier" in text
    assert "fill_outlier" not in text


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


def test_kinematic_markers_ignore_ds_telemetry_glitches() -> None:
    ticks = [
        {
            "tick": 1,
            "t_ms": 0,
            "spd_mph": 50.0,
            "lim_mph": 55.0,
            "lim_dist_m": 50.0,
            "p1_tgt": "STATION",
            "p1": {"dist_start_m": 40.8},
        },
        {
            "tick": 2,
            "t_ms": 50,
            "spd_mph": 49.0,
            "lim_mph": 55.0,
            "lim_dist_m": 48.0,
            "p1_tgt": "STATION",
            "p1": {"dist_start_m": -293.5},
        },
        {
            "tick": 3,
            "t_ms": 100,
            "spd_mph": 48.0,
            "lim_mph": 55.0,
            "lim_dist_m": 46.0,
            "p1_tgt": "STATION",
            "p1": {"dist_start_m": 40.3},
        },
        {
            "tick": 4,
            "t_ms": 150,
            "spd_mph": 47.0,
            "lim_mph": 55.0,
            "lim_dist_m": 44.0,
            "p1_tgt": "STATION",
            "p1": {"dist_start_m": -289.0},
        },
    ]
    markers = _kinematic_markers(ticks)
    assert [m for m in markers if m.get("kind") == "ds0"] == []


def test_kinematic_markers_dedup_station_apply_by_episode() -> None:
    ticks = [
        {
            "tick": 1,
            "t_ms": 0,
            "spd_mph": 55.0,
            "lim_mph": 55.0,
            "lim_dist_m": 300.0,
            "stn_dist_m": 280.0,
            "p1_tgt": "STATION",
            "p1": {
                "apply_now": True,
                "dist_start_m": 40.0,
                "detail": "Estación dist=280m",
            },
        },
        {
            "tick": 2,
            "t_ms": 1000,
            "spd_mph": 54.0,
            "lim_mph": 55.0,
            "lim_dist_m": 250.0,
            "stn_dist_m": 260.0,
            "p1_tgt": "STATION",
            "p1": {
                "apply_now": True,
                "dist_start_m": 35.0,
                "detail": "Estación dist=260m",
            },
        },
    ]
    markers = _kinematic_markers(ticks)
    apply = [m for m in markers if m.get("kind") == "apply"]
    assert len(apply) == 1


def test_station_event_rows_door_transitions() -> None:
    from tsw6v2.session_report import _station_event_rows

    ticks = [
        {
            "tick": 1,
            "t_ms": 0,
            "stn_dist_m": 12.0,
            "spd_mph": 0.0,
            "doors_telem": False,
            "doors_dmi": False,
        },
        {
            "tick": 2,
            "t_ms": 1000,
            "stn_dist_m": 12.0,
            "spd_mph": 0.0,
            "doors_telem": True,
            "doors_dmi": False,
            "stn_fsm": "STOPPED",
        },
        {
            "tick": 3,
            "t_ms": 2000,
            "stn_dist_m": 12.0,
            "spd_mph": 0.0,
            "doors_telem": False,
            "doors_dmi": False,
            "stn_fsm": "DEPARTING",
        },
    ]
    rows = _station_event_rows(ticks)
    door_rows = [r for r in rows if str(r.get("event", "")).startswith("puertas")]
    assert len(door_rows) == 2
    assert door_rows[0]["event"] == "puertas ABIERTAS"
    assert door_rows[1]["event"] == "puertas CERRADAS"


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


def test_enrich_ticks_active_time_skips_menu_pause() -> None:
    ticks = [
        {"seq": 1, "t_ms": 0},
        {"seq": 1, "t_ms": 60000},  # menú pausado: seq congelado
        {"seq": 2, "t_ms": 60050},
        {"seq": 4, "t_ms": 60100},
    ]
    enrich_ticks_active_time(ticks)
    assert ticks[-1]["active_t_ms"] == 150.0  # (4-1) * 50 ms


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
