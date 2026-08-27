"""Tests channel_diagnostics.py."""

from tsw6.telemetry.channel_diagnostics import (
    ControllerMetrics,
    LoopMetrics,
    acceptance_verdict,
    probe_mod_label,
    percentile,
)


def test_percentile() -> None:
    assert percentile([10.0, 20.0, 30.0, 40.0], 95) >= 30.0


def test_probe_mod_label_legacy() -> None:
    assert "LEGACY" in probe_mod_label(
        {"lever_notch": False, "last_cmd_id": False, "last_ack_ok": False,
         "brake_cyl_bar": False})


def test_acceptance_pass_idle() -> None:
    v = acceptance_verdict(
        loop=LoopMetrics(),
        channel={"cmd_total": 0, "ack_ok_pct": 0, "ack_p95_ms": 0},
        controller=ControllerMetrics(),
        telem_poll_hz=19.0,
        mod_flags={"lever_notch": True, "last_cmd_id": True,
                   "last_ack_ok": True, "brake_cyl_bar": False},
    )
    assert v == "PASS"


def test_acceptance_fail_ack() -> None:
    v = acceptance_verdict(
        loop=LoopMetrics(),
        channel={"cmd_total": 10, "ack_ok_pct": 20.0, "ack_p95_ms": 80},
        controller=ControllerMetrics(),
        telem_poll_hz=19.0,
        mod_flags={"lever_notch": True, "last_cmd_id": True,
                   "last_ack_ok": True, "brake_cyl_bar": False},
    )
    assert v == "FAIL"
