from __future__ import annotations

from pathlib import Path

from scripts.tools.amp import (
    analyze_probe_log,
    parse_probe_log,
    render_markdown_report,
)

FIXTURE = """# UE4SS probe — log de sesión
#
time_s,seq,hz,speed_mph,limit_mph,max_mph,handle_notch,power,train_brake,loco_brake,dyn_brake,accel_ms2,gradient_pct,amps,doors_telem,doors_dmi,mc_input,vehicle
0.0,1,20.0,0.00,30,,4,2.0,0,0,0,0.5,0,200.0,0,,0.5,RVM_TEST
# raw: seq=1 speed_ms=0 amps=200.0 brake_cyl_bar=9.5 vehicle=RVM_TEST
1.0,2,20.0,10.00,30,,4,0,0,0,0,-0.4,0,-300.0,0,,0.5,RVM_TEST
# raw: seq=2 speed_ms=4.5 amps=-300.0 vehicle=RVM_TEST
2.0,3,20.0,0.00,30,,4,0,0,0,0,0,0,2.0,0,,0.5,RVM_TEST
"""


def test_parse_and_classify(tmp_path: Path) -> None:
    p = tmp_path / "probe.txt"
    p.write_text(FIXTURE, encoding="utf-8")
    samples = parse_probe_log(p)
    assert len(samples) == 3
    rep = analyze_probe_log(p)
    assert rep.traction.count == 1
    assert rep.braking.count == 1
    assert rep.idle.count == 1
    assert rep.verdict() == "variable"
    assert rep.traction.max_a == 200.0
    assert rep.braking.min_a == -300.0


def test_markdown_report(tmp_path: Path) -> None:
    p = tmp_path / "probe.txt"
    p.write_text(FIXTURE, encoding="utf-8")
    rep = analyze_probe_log(p)
    md = render_markdown_report([rep])
    assert "Tracción" in md
    assert "Frenada" in md
