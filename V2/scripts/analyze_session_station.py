#!/usr/bin/env python3
"""Análisis rápido sesión station — arranque, stn, escenario."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: analyze_session_station.py <jsonl>", file=sys.stderr)
        return 1
    p = Path(args[0])
    ticks: list[dict] = []
    session: dict | None = None
    for line in p.read_text(encoding="utf-8").splitlines():
        o = json.loads(line)
        if o.get("type") == "session":
            session = o
        elif o.get("type") == "tick":
            ticks.append(o)

    print("SESSION:", session)
    print("ticks:", len(ticks))

    print("\n--- STARTUP (ticks 1-45) ---")
    for t in ticks[:45]:
        p1 = t.get("p1") or {}
        sig = t.get("signal_dist_m")
        print(
            f"  tick={t['tick']:4} seq={t.get('seq')} spd={t.get('spd_mph')} "
            f"stn={t.get('stn_dist_m')} p1tgt={t.get('p1_tgt')} "
            f"sig_red={t.get('signal_red')} sig_m={sig} "
            f"lim={t.get('lim_mph')} lim_m={t.get('lim_dist_m')} "
            f"why={p1.get('reason')} P={t.get('brake_cyl_bar')}"
        )

    first_stn = next((t for t in ticks if t.get("stn_dist_m") is not None), None)
    if first_stn:
        print(
            f"\nfirst stn_dist: tick={first_stn['tick']} "
            f"val={first_stn['stn_dist_m']} spd={first_stn.get('spd_mph')}"
        )

    prev_seq: int | None = None
    jumps: list[tuple] = []
    for t in ticks:
        s = t.get("seq")
        if s is None:
            continue
        if prev_seq is not None and int(s) < int(prev_seq) - 50:
            jumps.append((t["tick"], prev_seq, s))
        prev_seq = int(s)

    print(f"\nseq backward jumps (carga escenario?): {len(jumps)}")
    for j in jumps[:8]:
        print(" ", j)

    print("\np1_tgt:", dict(Counter(t.get("p1_tgt") for t in ticks)))
    print(
        "stn null/set:",
        sum(1 for t in ticks if t.get("stn_dist_m") is None),
        sum(1 for t in ticks if t.get("stn_dist_m") is not None),
    )
    print("p1 STATION ticks:", sum(1 for t in ticks if t.get("p1_tgt") == "STATION"))

    fst = next((t for t in ticks if t.get("p1_tgt") == "STATION"), None)
    if fst:
        print(
            "first STATION:",
            fst["tick"],
            "stn_m",
            fst.get("stn_dist_m"),
            "spd",
            fst.get("spd_mph"),
        )

    stn_ticks = [t for t in ticks if t.get("stn_dist_m") is not None]
    if stn_ticks:
        vals = [float(t["stn_dist_m"]) for t in stn_ticks]
        print(f"stn_dist range: {min(vals):.0f} .. {max(vals):.0f} m")
        # decreasing check when moving
        moving = [
            (stn_ticks[i]["tick"], stn_ticks[i - 1]["stn_dist_m"], stn_ticks[i]["stn_dist_m"])
            for i in range(1, min(200, len(stn_ticks)))
            if (stn_ticks[i].get("spd_mph") or 0) > 3
            and stn_ticks[i]["stn_dist_m"] != stn_ticks[i - 1]["stn_dist_m"]
        ]
        print("stn changes while moving (sample):", moving[:8])

    print("\nreasons top:", Counter((t.get("p1") or {}).get("reason") for t in ticks).most_common(10))
    spds = [float(t["spd_mph"]) for t in ticks if t.get("spd_mph") is not None]
    if spds:
        print(f"speed range: {min(spds):.1f} .. {max(spds):.1f} mph")

    fsm = Counter(t.get("stn_fsm") for t in ticks if t.get("stn_fsm"))
    print("stn_fsm:", dict(fsm))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
