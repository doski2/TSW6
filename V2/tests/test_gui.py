from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.gui import format_viewer_lines, snapshot_to_fields
from tsw6v2.gui_view import build_dashboard, snapshot_ai_payload
from tsw6v2.loop import AgentSnapshot


def test_format_viewer_lines_empty() -> None:
    assert format_viewer_lines(None) == ["(sin GetData — probe F7?)", "vel=—  lever=—  ipc_tgt=—", "veh=—"]


def test_format_viewer_lines_snapshot() -> None:
    snap = AgentSnapshot(
        tick=5,
        seq=10,
        speed_mph=22.0,
        lever_notch=4,
        target_notch=3,
        vehicle="Class323",
        train_brake=0.1,
    )
    lines = format_viewer_lines(snap, loop_hz=18.5)
    assert len(lines) == 3
    assert "seq 10" in lines[0]
    assert "22.0 mph" in lines[1]
    assert "Class323" in lines[2]


def test_snapshot_to_fields_p1_station() -> None:
    snap = AgentSnapshot(
        tick=12,
        speed_mph=8.0,
        limit_mph=55.0,
        limit_dist_m=400.0,
        station_dist_m=25.0,
        station_fsm="STOPPED",
        p1_target_kind="LIMIT",
        effective_limit_mph=50.0,
        p1_dist_start_m=320.0,
        p1_apply_now=True,
        p1_cmd="",
        p1_reason="p1_off",
        lever_notch=4,
    )
    f = snapshot_to_fields(snap, loop_hz=20.0, p1_mode="p1", planning_source="http")
    assert f.station == "25 m"
    assert f.fsm == "STOPPED"
    assert f.p1_target == "LIMIT"
    assert f.p1_eff == "50 mph"
    assert f.p1_ds == "320 m"
    assert f.p1_apply == "Y"
    assert f.planning == "http"
    assert "55" in f.limit


def test_loop_station_planning_source() -> None:
    from tsw6v2.loop import AgentLoop
    from tsw6v2.p1_mode import apply_p1_mode

    loop = AgentLoop()
    assert loop.station_planning_source in ("http", "file", "none")
    apply_p1_mode(loop, "station")
    assert loop.station_planning_channel  # HTTP o Planning.txt según entorno


def test_build_dashboard_three_domains() -> None:
    snap = AgentSnapshot(
        tick=100,
        speed_mph=58.0,
        gradient_pct=-0.6,
        limit_mph=60.0,
        limit_dist_m=800.0,
        effective_limit_mph=59.5,
        station_dist_m=1200.0,
        p1_target_kind="SPEED_LIMIT",
        p1_layer="HOLD_DH",
        p1_reason="downhill_hold",
        lever_notch=5,
    )
    d = build_dashboard(snap, loop_hz=20.0, p1_mode="p1", planning_source="http")
    assert d.limit.enabled
    assert d.station.enabled
    assert d.downhill.is_downhill
    assert d.downhill.hold_active
    assert d.limit.is_target


def test_snapshot_ai_payload_reuses_dashboard() -> None:
    snap = AgentSnapshot(tick=3, seq=7, speed_mph=40.0, limit_mph=55.0, limit_dist_m=200.0)
    dash = build_dashboard(snap, p1_mode="p1")
    payload = snapshot_ai_payload(snap, dashboard=dash)
    assert payload["tick"] == 3
    assert payload["seq"] == 7
    assert payload["cartel"]["limit_mph"] == 55.0


def test_snapshot_ai_payload_structure() -> None:
    snap = AgentSnapshot(tick=1, speed_mph=40.0, limit_mph=55.0, limit_dist_m=200.0)
    off = snapshot_ai_payload(snap, p1_mode="off")
    assert off["cartel"]["enabled"] is False
    assert off["estacion"]["enabled"] is False
    on = snapshot_ai_payload(snap, p1_mode="p1")
    assert "cartel" in on and "bajada" in on and "estacion" in on and "p1" in on
    assert on["cartel"]["enabled"] is True
    assert on["estacion"]["enabled"] is True


def test_gui_mode_aliases_unified() -> None:
    from tsw6v2.p1_mode import gui_mode_to_loop_mode, resolve_gui_p1_mode

    assert resolve_gui_p1_mode("limit") == "p1"
    assert resolve_gui_p1_mode("station") == "p1"
    assert resolve_gui_p1_mode("off") == "off"
    assert gui_mode_to_loop_mode("p1") == "station"
    assert gui_mode_to_loop_mode("off") == "console"
