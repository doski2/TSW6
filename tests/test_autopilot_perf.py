"""Rendimiento autopilot: parseo de heartbeat/canal."""
from __future__ import annotations

from tsw6.telemetry.autopilot_perf import analyze_log_text, evaluate, why_cpu


_HB = (
    "02:38:19.384 [tsw.autopilot ] INFO    heartbeat modo=ue4ss  "
    "loop_hz=19.9  work=34ms  sleep=12ms  tgt=20Hz  spd=50.1  lim=60  "
    "next_lim=55  lim2=—  elim=60.0  seq=336  dist=1.4 mi  probe=1.6 mi  "
    "frozen=N  stale=Y  mandos=ipc  ctrl=active  p1on=Y  telem=ue4ss  "
    "age=20ms  telem_poll=16.1Hz  lua=0 dmi=—  cmd_q=0 id=0 cf=— ack=0ms "
    "ret=0 err=— via=— match=— lever=6 hud=6\n"
)
_CANAL = (
    "02:38:21.248 [tsw.autopilot ] INFO    canal [PASS]  ipc_ok=0/0 (0%)  "
    "http_ok=0  via=—  ack_p95=0ms  enq=0 ret=0 drop=0 err=—  async=0 KEY=0 "
    "p1rej=0  ticks=200 work_max=40ms slow=0  loop_hz=19.7-20.0  "
    "telem_poll=16.4Hz  mod=lever_notch+last_cmd_id+last_ack_ok falta=brake_cyl_bar\n"
)


def test_heartbeat_cpu_duty() -> None:
    stats = analyze_log_text(_HB * 4 + _CANAL)
    assert stats["n_heartbeat"] == 4
    assert abs(stats["work_med_ms"] - 34) < 0.1
    assert abs(stats["sleep_med_ms"] - 12) < 0.1
    assert stats["cpu_core_pct"] is not None
    # 34/(34+12) ≈ 74 %
    assert 70 < stats["cpu_core_pct"] < 78
    assert evaluate(stats) == []
    why = why_cpu(stats)
    assert any("hilo de control" in w for w in why)


def test_slow_loop_fails() -> None:
    slow = _HB.replace("loop_hz=19.9", "loop_hz=8.0").replace("work=34ms", "work=80ms")
    stats = analyze_log_text(slow * 3)
    fails = evaluate(stats)
    assert fails
