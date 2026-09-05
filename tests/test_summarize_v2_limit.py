from __future__ import annotations

import json
from pathlib import Path

from tsw6v2.session_report import summarize, write_html_replay


def test_summarize_fixture(tmp_path: Path) -> None:
    p = tmp_path / "s.jsonl"
    rows = [
        {"type": "session", "mode": "limit", "route": "test"},
        {
            "type": "tick",
            "tick": 1,
            "t_ms": 0,
            "spd_mph": 58.0,
            "lever": 4,
            "target": 3,
            "lim_mph": 55.0,
            "lim_dist_m": 200.0,
            "eff_mph": 60.0,
            "p1": {
                "cmd": "APPLY",
                "phase": "B1",
                "dist_start_m": 10.0,
                "apply_now": True,
                "reason": "plan",
            },
            "ipc": {"sent": True, "ok": True},
        },
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    data = summarize(p)
    assert data["apply_ticks"] == 1
    html = tmp_path / "out.html"
    write_html_replay(p, html)
    assert "Replay P1" in html.read_text(encoding="utf-8")
