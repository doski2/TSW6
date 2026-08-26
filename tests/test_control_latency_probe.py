"""Tests control_latency_probe — estadísticas sin juego."""

from tsw6.telemetry.control_latency_probe import (
    LatencyRow,
    percentile,
    summarize_rows,
)


def test_percentile():
    assert percentile([10.0, 20.0, 30.0, 40.0], 50) == 25.0
    assert percentile([100.0], 95) == 100.0


def test_summarize_rows_empty():
    s = summarize_rows([])
    assert s["n_cmds"] == 0


def test_summarize_rows_ok():
    rows = [
        LatencyRow(
            cmd_id=1, target_notch=3, notch_before=4,
            ack_ok=True, ack_error="", ack_ms=18.0,
            telem_notch=3, telem_seq=10, telem_ms=45.0,
            roundtrip_ms=45.0, getdata_age_ms=12.0,
        ),
        LatencyRow(
            cmd_id=2, target_notch=2, notch_before=3,
            ack_ok=True, ack_error="", ack_ms=22.0,
            telem_notch=2, telem_seq=11, telem_ms=80.0,
            roundtrip_ms=80.0, getdata_age_ms=8.0,
        ),
        LatencyRow(
            cmd_id=3, target_notch=1, notch_before=2,
            ack_ok=False, ack_error="ack_timeout", ack_ms=120.0,
            telem_notch=2, telem_seq=11, telem_ms=None,
            roundtrip_ms=None, getdata_age_ms=30.0,
        ),
    ]
    s = summarize_rows(rows)
    assert s["n_cmds"] == 3
    assert s["ack_ok_pct"] < 100.0
    assert s["telem_match_pct"] < 100.0
    assert s["ack_ms"]["n"] == 2
    assert s["roundtrip_ms"]["p50"] == 62.5
