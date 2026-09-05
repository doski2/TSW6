#!/usr/bin/env python3
"""CLI — resumen JSONL sesión P1 (envuelve tsw6v2.session_report)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_V2 = _ROOT / "V2"
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

from tsw6v2.session_report import (
    finalize_session_report,
    print_report,
    summarize,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Resumen JSONL sesión P1 V2")
    ap.add_argument("jsonl", type=Path, help="logs/v2/*.jsonl")
    ap.add_argument("--json", action="store_true", help="salida JSON")
    ap.add_argument(
        "--html",
        nargs="?",
        const="",
        metavar="PATH",
        help="genera replay HTML (default: mismo nombre .html)",
    )
    args = ap.parse_args()
    data = summarize(args.jsonl)
    if args.html is not None:
        html_path = (
            args.jsonl.with_suffix(".html")
            if args.html == ""
            else Path(args.html)
        )
        finalize_session_report(args.jsonl, html_path=html_path, force=True)
        print(f"replay -> {html_path.resolve()}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.html is None:
        print_report(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
