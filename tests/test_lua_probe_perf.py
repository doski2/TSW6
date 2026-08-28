"""Rendimiento Lua: parseo de UE4SS.log (sin juego)."""
from __future__ import annotations

from tsw6.telemetry.lua_probe_perf import (
    analyze_log_text,
    evaluate_lua_perf,
    parse_probe_seq_events,
)


def _line(ts: str, seq: int) -> str:
    return (
        f"[{ts}] [Lua] [TelemetryProbe] seq={seq} speed_ms=20.0 "
        "power=2 handle_notch=6 vehicle=Class323\n"
    )


def test_parse_seq_and_steady_hz_near_20() -> None:
    # Logs cada 2 s, +34 seq → ~17 Hz (régimen bueno, sin hitch 1→2).
    text = "".join([
        _line("2026-08-28 00:10:47.4191394", 34),
        _line("2026-08-28 00:10:49.4191394", 68),
        _line("2026-08-28 00:10:51.4191394", 102),
        _line("2026-08-28 00:10:53.4191394", 136),
    ])
    events = parse_probe_seq_events(text)
    assert len(events) == 4
    stats, _ = analyze_log_text(text)
    assert stats["steady_hz"] is not None
    assert abs(stats["steady_hz"] - 17.0) < 0.2
    assert evaluate_lua_perf(stats) == []


def test_hitch_seq1_to_seq2_is_warning_not_fail() -> None:
    text = (
        _line("2026-08-28 00:10:42.6992347", 1)
        + _line("2026-08-28 00:10:45.3698836", 2)
        + _line("2026-08-28 00:10:47.4191394", 34)
        + _line("2026-08-28 00:10:49.4191394", 68)
    )
    stats, _ = analyze_log_text(text)
    assert stats["hitch_s"] is not None
    assert stats["hitch_s"] > 2.5
    assert evaluate_lua_perf(stats) == []


def test_low_steady_hz_fails() -> None:
    text = "".join([
        _line("2026-08-28 00:10:47.4191394", 34),
        _line("2026-08-28 00:10:57.4191394", 40),
    ])
    stats, _ = analyze_log_text(text)
    fails = evaluate_lua_perf(stats)
    assert any("Hz estable" in f for f in fails)


def test_perf_line_avg_ms() -> None:
    text = (
        _line("2026-08-28 00:10:47.0000000", 34)
        + "[2026-08-28 00:10:47.001] [Lua] "
        "[TelemetryProbe] perf writes=34 avg_ms=1.20 hz=17.0 span=2.00s\n"
        + _line("2026-08-28 00:10:49.0000000", 68)
    )
    _, rows = analyze_log_text(text)
    assert len(rows) == 1
    assert rows[0]["avg_ms"] == 1.2
    assert rows[0]["writes"] == 34
