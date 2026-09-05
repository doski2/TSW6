#!/usr/bin/env python3
"""Summarize HUD_GetAmmeter captures in an ApiExplorer session (L0.6f).

Usage:
  python scripts/tools/summarize_hud_amps.py data/lab_exports/exports/<session>
  python scripts/tools/summarize_hud_amps.py SESSION_DIR --json --write-report

Reads hud_batch.json and hud_batch_*.json. Prints a table of Amps vs power/dyn_brake.
Exit 0 if any Amps != 0 (candidate for probe); exit 2 if all zero; exit 1 on error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tsw6.lab.lab_export import (  # noqa: E402
    AMPS_CAPTURE_STEPS,
    amps_session_verdict,
    summarize_amps_session,
)


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def render_markdown_report(session_dir: Path, rows: list[dict], verdict: str) -> str:
    session_id = session_dir.name
    lines = [
        f"# Amperímetro L0.6f — {session_id}",
        "",
        f"- Carpeta: `{session_dir}`",
        f"- Capturas: **{len(rows)}**",
        f"- Veredicto: **{verdict}**",
        "",
        "## Tabla",
        "",
        "| Archivo | Amps | speed_ms | power | dyn_brake | train_brake | accel | TractiveEffort N |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| `{file}` | {amps} | {speed_ms} | {power} | {dyn_brake} | {train_brake} | "
            "{accel_ms2} | {tractive_effort_n} |".format(
                file=row.get("file", "?"),
                amps=_fmt(row.get("amps")),
                speed_ms=_fmt(row.get("speed_ms")),
                power=_fmt(row.get("power")),
                dyn_brake=_fmt(row.get("dyn_brake")),
                train_brake=_fmt(row.get("train_brake")),
                accel_ms2=_fmt(row.get("accel_ms2")),
                tractive_effort_n=_fmt(row.get("tractive_effort_n")),
            )
        )
    lines.extend(
        [
            "",
            "## Protocolo sugerido (si faltan filas)",
            "",
        ]
    )
    for suffix, desc in AMPS_CAPTURE_STEPS:
        lines.append(f"- `hud_batch_{suffix}.json` — {desc}")
    lines.append("")
    if verdict == "variable":
        lines.append(
            "**Siguiente paso:** cablear `amps` en TelemetryProbeMod (D2) y correlar con `dyn_brake`."
        )
    elif verdict == "always_zero":
        lines.append(
            "**Siguiente paso:** marcar `HUD_GetAmmeter` como catálogo en 323; frenado sigue con "
            "`dyn_brake` + cilindro."
        )
    else:
        lines.append(
            "**Siguiente paso:** pulsar F5 en cabina (filas arriba) y copiar `hud_batch.json` "
            "a `hud_batch_<situacion>.json`."
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path, help="ApiExplorer export session folder")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of table")
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write amps_report.md in the session folder",
    )
    args = parser.parse_args()

    session_dir = args.session_dir.resolve()
    if not session_dir.is_dir():
        print(f"ERROR: not a directory: {session_dir}", file=sys.stderr)
        return 1

    rows = summarize_amps_session(session_dir)
    verdict = amps_session_verdict(rows)

    if args.json:
        print(
            json.dumps(
                {"session_id": session_dir.name, "verdict": verdict, "rows": rows},
                indent=2,
            )
        )
    else:
        if not rows:
            print(f"No hud_batch*.json in {session_dir}")
            print("\nSuggested captures:")
            for suffix, desc in AMPS_CAPTURE_STEPS:
                print(f"  hud_batch_{suffix}.json — {desc}")
        else:
            print(f"Session {session_dir.name} — verdict: {verdict}\n")
            header = f"{'file':<28} {'Amps':>8} {'speed':>8} {'power':>8} {'dyn_br':>8} {'train_br':>8} {'TE N':>8}"
            print(header)
            print("-" * len(header))
            for row in rows:
                print(
                    f"{row.get('file', '?'):<28} "
                    f"{_fmt(row.get('amps')):>8} "
                    f"{_fmt(row.get('speed_ms')):>8} "
                    f"{_fmt(row.get('power')):>8} "
                    f"{_fmt(row.get('dyn_brake')):>8} "
                    f"{_fmt(row.get('train_brake')):>8} "
                    f"{_fmt(row.get('tractive_effort_n')):>8}"
                )

    if args.write_report:
        report = render_markdown_report(session_dir, rows, verdict)
        out_path = session_dir / "amps_report.md"
        out_path.write_text(report, encoding="utf-8")
        print(f"\nWrote {out_path}")

    if verdict == "variable":
        return 0
    if verdict in ("always_zero", "no_captures", "no_amps_field"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
