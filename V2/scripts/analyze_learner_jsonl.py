#!/usr/bin/env python3
"""Resumen aprendizaje / aire en sesiones JSONL (L4 lite)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def _stats(xs: list[float]) -> dict | None:
    if not xs:
        return None
    xs = sorted(xs)
    return {
        "n": len(xs),
        "min": round(xs[0], 2),
        "med": round(xs[len(xs) // 2], 2),
        "max": round(xs[-1], 2),
    }


def analyze(path: Path) -> dict:
    session: dict = {}
    n = 0
    reasons: Counter[str] = Counter()
    air_fill = 0
    fb_ticks = 0
    fb_shortfall = 0
    fb_escalated = 0
    fb_with_obs = 0
    fb_with_pred = 0
    apply_ticks = 0
    brake_ticks = 0
    cyl_when_brake: list[float] = []
    fill_first = None
    fill_last = None
    fill_n_last = None
    decel_n_last = None
    learn_events = 0
    learn_accepted = 0
    learn_rejects: Counter[str] = Counter()
    profile = None
    vehicle = None
    b1_gate = 1.55 * 0.92

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("type") == "session":
            session = o
            profile = o.get("profile")
            continue
        if o.get("type") != "tick":
            continue
        n += 1
        vehicle = o.get("vehicle") or vehicle
        p1 = o.get("p1") or {}
        reason = p1.get("reason") or ""
        reasons[reason] += 1
        if reason == "air_fill":
            air_fill += 1
        if p1.get("cmd") == "APPLY":
            apply_ticks += 1
        lever = o.get("lever")
        cyl = o.get("brake_cyl_bar")
        if lever is not None and int(lever) < 4:
            brake_ticks += 1
            if cyl is not None:
                cyl_when_brake.append(float(cyl))
        fs = o.get("brake_fill_s")
        if fs is not None:
            if fill_first is None:
                fill_first = float(fs)
            fill_last = float(fs)
        if o.get("brake_fill_n") is not None:
            fill_n_last = int(o["brake_fill_n"])
        if o.get("decel_observe_n") is not None:
            decel_n_last = int(o["decel_observe_n"])
        if o.get("learn_kind"):
            learn_events += 1
            if o.get("learn_accepted"):
                learn_accepted += 1
            elif o.get("learn_reject_reason"):
                learn_rejects[o["learn_reject_reason"]] += 1
        fb = o.get("fb")
        if fb:
            fb_ticks += 1
            if fb.get("shortfall"):
                fb_shortfall += 1
            if fb.get("escalated"):
                fb_escalated += 1
            if fb.get("a_obs_ms2") is not None:
                fb_with_obs += 1
            if fb.get("a_pred_ms2") is not None:
                fb_with_pred += 1

    brake_below = sum(1 for x in cyl_when_brake if x < b1_gate)
    return {
        "file": path.name,
        "ticks": n,
        "profile": profile,
        "vehicle": vehicle,
        "git": session.get("git"),
        "fill_first": fill_first,
        "fill_last": fill_last,
        "fill_n_last": fill_n_last,
        "decel_n_last": decel_n_last,
        "air_fill": air_fill,
        "apply": apply_ticks,
        "brake_lever": brake_ticks,
        "cyl_below_b1_gate": brake_below,
        "fb_ticks": fb_ticks,
        "fb_obs": fb_with_obs,
        "fb_pred": fb_with_pred,
        "fb_shortfall": fb_shortfall,
        "fb_escalated": fb_escalated,
        "learn_events": learn_events,
        "learn_accepted": learn_accepted,
        "learn_rejects": learn_rejects.most_common(6),
        "top_reasons": reasons.most_common(6),
        "cyl_brake": _stats(cyl_when_brake),
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(__file__).resolve().parents[2]
    log_dir = root / "logs" / "v2"
    files = [Path(p) for p in args] if args else sorted(
        log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not files:
        print(f"No JSONL in {log_dir}", file=sys.stderr)
        return 1

    print(f"Analyzing {len(files)} session(s)\n")
    for path in files[:10]:
        if not path.is_file():
            print(f"skip missing {path}")
            continue
        r = analyze(path)
        print(f"=== {r['file']} ===")
        print(f"  ticks={r['ticks']} profile={r['profile']} git={r['git']}")
        print(f"  vehicle={r['vehicle']}")
        print(
            f"  brake_fill_s: {r['fill_first']} -> {r['fill_last']} "
            f"(n_last={r['fill_n_last']}, decel_n_last={r['decel_n_last']})"
        )
        print(
            f"  air_fill={r['air_fill']} APPLY={r['apply']} "
            f"lever_brake={r['brake_lever']} cyl<B1={r['cyl_below_b1_gate']}"
        )
        print(
            f"  fb: n={r['fb_ticks']} obs={r['fb_obs']} pred={r['fb_pred']} "
            f"shortfall={r['fb_shortfall']} escalated={r['fb_escalated']}"
        )
        print(
            f"  learn: events={r['learn_events']} accepted={r['learn_accepted']} "
            f"rejects={r['learn_rejects']}"
        )
        print(f"  cyl_brake: {r['cyl_brake']}")
        print("  reasons:", ", ".join(f"{k}={v}" for k, v in r["top_reasons"]))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
