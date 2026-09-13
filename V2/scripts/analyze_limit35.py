"""Analiza overspeed en zona lim_mph=35 de un JSONL."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"c:\Users\doski\TSW6\logs\v2\20260913T214610Z_cross-city_station.jsonl"
    )
    ticks: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("type") == "tick":
            ticks.append(row)

    lim35 = [t for t in ticks if t.get("lim_mph") == 35]
    print(f"total ticks: {len(ticks)}")
    print(f"ticks lim_mph=35: {len(lim35)}")

    overs = [
        t
        for t in ticks
        if t.get("lim_mph") == 35
        and t.get("spd_mph") is not None
        and t.get("eff_mph") is not None
        and float(t["spd_mph"]) > float(t["eff_mph"]) + 0.5
    ]
    print(f"overspeed vs eff (lim35): {len(overs)}")
    if overs:
        mx = max(overs, key=lambda x: float(x.get("spd_mph") or 0))
        print(
            f"max overspeed: {mx.get('spd_mph')} mph @ tick {mx['tick']} "
            f"eff={mx.get('eff_mph')} lim_dist={mx.get('lim_dist_m')}"
        )

    prev_lim = None
    print("\n=== Transiciones a lim=35 ===")
    for t in ticks:
        lim = t.get("lim_mph")
        if lim == 35 and prev_lim != 35:
            p1 = t.get("p1") or {}
            print(
                f"tick={t['tick']} spd={t.get('spd_mph')} eff={t.get('eff_mph')} "
                f"lim_d={t.get('lim_dist_m')} tgt={t.get('p1_tgt')} "
                f"cmd={p1.get('cmd')} why={p1.get('reason')} "
                f"apply={p1.get('apply_now')} ds={p1.get('dist_start_m')} "
                f"from_lim={prev_lim}"
            )
        prev_lim = lim

    print("\n=== Overspeed samples (lim35) ===")
    for t in overs[:15]:
        p1 = t.get("p1") or {}
        print(
            f"tick={t['tick']} spd={t.get('spd_mph')} eff={t.get('eff_mph')} "
            f"lim_d={t.get('lim_dist_m')} cmd={p1.get('cmd')} why={p1.get('reason')} "
            f"layer={p1.get('layer')} tgt={t.get('p1_tgt')}"
        )

    # Window around worst overspeed
    if overs:
        mx_tick = max(overs, key=lambda x: float(x.get("spd_mph") or 0))["tick"]
        print(f"\n=== Ventana tick {mx_tick - 20}..{mx_tick + 20} ===")
        for t in ticks:
            if mx_tick - 20 <= t["tick"] <= mx_tick + 20:
                p1 = t.get("p1") or {}
                print(
                    f"tick={t['tick']} spd={t.get('spd_mph')} eff={t.get('eff_mph')} "
                    f"lim={t.get('lim_mph')} lim_d={t.get('lim_dist_m')} "
                    f"cmd={p1.get('cmd')}/{p1.get('phase')} why={p1.get('reason')} "
                    f"apply={p1.get('apply_now')} ds={p1.get('dist_start_m')}"
                )
    sub = [t for t in ticks if t.get("lim_mph") == 35]
    if sub:
        print("\n=== Perfil lim_mph=35 ===")
        print(f"range ticks {sub[0]['tick']} - {sub[-1]['tick']}")
        for dist in [4000, 3000, 2000, 1000, 500, 300, 200, 100, 50, 0]:
            near = min(sub, key=lambda t: abs((t.get("lim_dist_m") or 0) - dist))
            p1 = near.get("p1") or {}
            print(
                f"~{dist}m: tick={near['tick']} spd={near.get('spd_mph')} "
                f"eff={near.get('eff_mph')} lim_d={near.get('lim_dist_m')} "
                f"cmd={p1.get('cmd')} why={p1.get('reason')} ds={p1.get('dist_start_m')}"
            )
        for t in sub:
            if (t.get("eff_mph") or 99) < 60:
                p1 = t.get("p1") or {}
                print(
                    f"first eff<60: tick={t['tick']} spd={t.get('spd_mph')} "
                    f"eff={t.get('eff_mph')} lim_d={t.get('lim_dist_m')} why={p1.get('reason')}"
                )
                break
        else:
            print("eff never < 60 while lim_mph=35")

        bad = [
            t
            for t in sub
            if (t.get("spd_mph") or 0) > 38
            and (t.get("lim_dist_m") or 9999) < 500
        ]
        print(f"spd>38 within 500m of 35 sign: {len(bad)} ticks")
        if bad:
            mx = max(bad, key=lambda x: float(x.get("spd_mph") or 0))
            p1 = mx.get("p1") or {}
            print(
                f"worst: tick={mx['tick']} spd={mx.get('spd_mph')} eff={mx.get('eff_mph')} "
                f"lim_d={mx.get('lim_dist_m')} why={p1.get('reason')} cmd={p1.get('cmd')}"
            )

    print("\n=== Frenada 500m a cartel ===")
    for t in ticks:
        if not (t.get("lim_mph") == 35 and 15790 <= t["tick"] <= 16260):
            continue
        p1 = t.get("p1") or {}
        if t["tick"] % 25 == 0 or t["tick"] in (
            15804,
            15805,
            15971,
            16063,
            16157,
            16204,
            16251,
        ):
            print(
                f"tick={t['tick']} spd={t.get('spd_mph')} lim_d={t.get('lim_dist_m')} "
                f"lev={t.get('lever')} brk={t.get('train_brake')} "
                f"cmd={p1.get('cmd')}/{p1.get('phase')} why={p1.get('reason')} "
                f"ds={p1.get('dist_start_m')} apply={p1.get('apply_now')}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
