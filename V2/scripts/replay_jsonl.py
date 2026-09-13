#!/usr/bin/env python3
"""Replay offline de sesión P1 desde JSONL — re-evalúa decisiones tick a tick."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "V2")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeReleaseState
from tsw6v2.constants import MS_TO_MPH
from tsw6v2.decision import evaluate_p1_tick
from tsw6v2.learner import LearnerProfile
from tsw6v2.limits import LimitBrakeState


def _tick_to_snap(t: dict[str, Any]) -> ProbeSnapshot:
    spd = t.get("spd_mph")
    eff = t.get("eff_mph")
    lim = t.get("lim_mph")
    lim_d = t.get("lim_dist_m")
    sig_d = t.get("signal_dist_m")
    return ProbeSnapshot.from_dict(
        {
            "seq": t.get("seq"),
            "speed_ms": float(spd) / MS_TO_MPH if spd is not None else None,
            "lever_notch": t.get("lever"),
            "brake_cyl_bar": t.get("brake_cyl_bar"),
            "gradient_pct": t.get("grad_pct"),
            "speed_limit_ms": float(eff) / MS_TO_MPH if eff is not None else None,
            "dist_limit_cm": float(lim_d) * 100.0 if lim_d is not None else None,
            "next_limit_ms": float(lim) / MS_TO_MPH if lim is not None else None,
            "signal_red": t.get("signal_red"),
            "signal_dist_cm": float(sig_d) * 100.0 if sig_d is not None else None,
            "vehicle": t.get("vehicle") or "?",
        }
    )


def replay(
    path: Path,
    *,
    zone_mph: Optional[float] = None,
    zone_over_mph: float = 0.5,
) -> dict[str, Any]:
    ticks = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    session = next((r for r in ticks if r.get("type") == "session"), {})
    tick_rows = [r for r in ticks if r.get("type") == "tick"]

    limit_state = LimitBrakeState()
    release_state = BrakeReleaseState()
    learner = LearnerProfile()

    max_spd_zone = 0.0
    zone_overspeed = 0
    air_fill = 0
    release_cmds = 0
    no_plan = 0
    bad_release_creep = 0
    lim_null_eff15 = 0
    lim_null_signal_flip = 0

    for t in tick_rows:
        snap = _tick_to_snap(t)
        if snap.speed_ms is None:
            continue

        stn = t.get("stn_dist_m")
        station_m = float(stn) if stn is not None and stn > 0 else None

        dec = evaluate_p1_tick(
            limit_state,
            release_state,
            snap,
            learner=learner,
            station_distance_m=station_m,
        )
        spd = float(t.get("spd_mph") or 0.0)
        eff = t.get("eff_mph")
        reason = dec.reason or ""
        tgt = dec.target_kind or ""

        if zone_mph is not None and eff == zone_mph:
            if spd > zone_mph + zone_over_mph:
                zone_overspeed += 1
                max_spd_zone = max(max_spd_zone, spd)
        if reason == "air_fill":
            air_fill += 1
        if reason == "release":
            release_cmds += 1
            sig_d = t.get("signal_dist_m")
            if (
                t.get("signal_red") is True
                and sig_d is not None
                and float(sig_d) > 50.0
                and spd < 8.0
            ):
                bad_release_creep += 1
        if reason == "no_plan":
            no_plan += 1

        if eff == 15.0 and t.get("lim_mph") is None:
            lim_null_eff15 += 1
            if tgt == "SIGNAL" and reason not in ("emergency",):
                lim_null_signal_flip += 1

    return {
        "path": str(path),
        "mode": session.get("mode"),
        "route": session.get("route"),
        "ticks": len(tick_rows),
        "zone_mph": zone_mph,
        "zone_overspeed_ticks": zone_overspeed,
        "zone_max_spd_mph": round(max_spd_zone, 2),
        "air_fill": air_fill,
        "release": release_cmds,
        "bad_release_creep_signal": bad_release_creep,
        "no_plan": no_plan,
        "lim_null_eff15": lim_null_eff15,
        "lim_null_signal_flip": lim_null_signal_flip,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay P1 offline desde JSONL")
    parser.add_argument("jsonl", type=Path)
    parser.add_argument(
        "--zone",
        type=float,
        default=15.0,
        help="Posted mph para métrica overspeed (default 15)",
    )
    args = parser.parse_args()
    stats = replay(args.jsonl, zone_mph=args.zone)
    print(f"Replay: {stats['path']}")
    print(f"  ticks: {stats['ticks']}  mode={stats['mode']}  route={stats['route']}")
    if stats["zone_mph"] is not None:
        print(
            f"  zona {stats['zone_mph']} mph >{stats['zone_mph']+0.5}: "
            f"{stats['zone_overspeed_ticks']} ticks (max {stats['zone_max_spd_mph']} mph)"
        )
    print(f"  air_fill: {stats['air_fill']}")
    print(f"  release: {stats['release']}  creep+rojo lejos: {stats['bad_release_creep_signal']}")
    print(f"  no_plan: {stats['no_plan']}")
    print(
        f"  lim=null eff=15: {stats['lim_null_eff15']} "
        f"(flip SIGNAL: {stats['lim_null_signal_flip']})"
    )


if __name__ == "__main__":
    main()
