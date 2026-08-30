#!/usr/bin/env python3
"""
api_correlator.py — Cruza http_guess de exports ApiExplorer con GET HTTPAPI en vivo.

Uso:
  python scripts/tools/api_correlator.py data/lab_exports/exports/20260830T145544Z
  python scripts/tools/api_correlator.py SESSION_DIR --hud-only --min-exact 0.8
  python scripts/tools/api_correlator.py SESSION_DIR --formation

Escribe correlation_report.md en la carpeta de sesión.
Con --formation escribe formation_http.json y formation_report.md.
Requiere TSW6 con -HTTPAPI y CommAPIKey.txt (salvo --dry-list).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tsw6.telemetry.tsw_api_client import TswApiClient, client_from_key_file  # noqa: E402

MatchKind = Literal["exact", "fuzzy", "mismatch", "skipped", "http_error", "no_data"]

EXPORT_FILES = (
    "hud_batch.json",
    "controls.json",
    "driver_aid.json",
    "formation.json",
)

SENTINEL = 3.4028235e38

# Espejo de config.lua — fallback si formation.json no trae http_probe (build < i).
FORMATION_PROBE_SPECS: list[tuple[str, str, str]] = []
for _node in (
    "BrakeCylinder_2_1",
    "BrakeCylinder_Direct_P",
    "BrakeCylinder_1_1",
    "MR (AirPipe)",
    "ClampPowerInput",
    "LoadSensingBrakeModifier",
    "Axle_1_1",
    "Axle_2_1",
    "ParkingBrakeCylinder",
):
    _fields = (
        ("Pressure_BAR", "pressure"),
        ("Pressure", "pressure"),
        ("Mass", "mass"),
        ("Mass_kg", "mass"),
        ("TotalDistanceTravelled_M", "odo"),
        ("CurrentTrackAdhesion", "adhesion"),
        ("IsSlipping", "adhesion"),
        ("Slip", "adhesion"),
        ("SlipSpeed", "adhesion"),
    )
    for _field, _kind in _fields:
        if _node.startswith("BrakeCylinder") or _node == "ParkingBrakeCylinder" or _node == "MR (AirPipe)":
            if _kind != "pressure":
                continue
        elif _node.startswith("Axle"):
            if _kind not in ("odo", "mass", "adhesion"):
                continue
        elif _kind not in ("mass",):
            continue
        FORMATION_PROBE_SPECS.append((_node, _field, _kind))


@dataclass
class GuessRow:
    path: str
    expected: Any
    source: str
    actual: Any = None
    api_path: Optional[str] = None
    match: MatchKind = "skipped"
    note: str = ""


@dataclass
class CorrelationSummary:
    rows: list[GuessRow] = field(default_factory=list)
    http_alive: bool = False
    session_id: str = ""

    @property
    def compared(self) -> list[GuessRow]:
        return [r for r in self.rows if r.match not in ("skipped",)]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in self.rows:
            out[row.match] = out.get(row.match, 0) + 1
        return out

    def hud_exact_ratio(self) -> Optional[float]:
        hud = [
            r
            for r in self.rows
            if r.source == "hud_batch.json" and r.match in ("exact", "fuzzy", "mismatch", "http_error", "no_data")
        ]
        if not hud:
            return None
        exact = sum(1 for r in hud if r.match == "exact")
        return exact / len(hud)


@dataclass
class FormationProbeRow:
    path: str
    scope: str
    node: str
    field: str
    actual: Any = None
    api_path: Optional[str] = None
    status: Literal["ok", "http_error", "no_data", "skipped"] = "skipped"
    note: str = ""
    lua_index_ok: Optional[bool] = None
    lua_fields: Optional[dict[str, Any]] = None


@dataclass
class FormationSnapshot:
    session_id: str
    http_alive: bool = False
    rows: list[FormationProbeRow] = field(default_factory=list)
    build: str = ""

    def ok_paths(self) -> list[FormationProbeRow]:
        return [r for r in self.rows if r.status == "ok"]

    def best_pressure_bar(self) -> Optional[tuple[str, float]]:
        for node in ("BrakeCylinder_2_1", "BrakeCylinder_Direct_P", "BrakeCylinder_1_1"):
            for row in self.rows:
                if row.node != node or row.field != "Pressure_BAR" or row.status != "ok":
                    continue
                val = unwrap_http_scalar(row.actual)
                if isinstance(val, (int, float)):
                    return row.path, float(val)
        return None


def normalize_api_path_candidates(lab_path: str) -> list[str]:
    """Convierte rutas http_guess del mod a candidatos GET /get/..."""
    raw = str(lab_path or "").strip()
    if not raw:
        return []

    candidates: list[str] = [raw]

    if "/Function." in raw:
        candidates.append(raw.replace("/Function.", ".Function."))

    if raw.startswith("CurrentFormation/0/") and not raw.startswith("CurrentFormation/0."):
        tail = raw[len("CurrentFormation/0/") :]
        candidates.append(f"CurrentFormation/0.{tail.replace('/', '.')}")

    if raw.startswith("CurrentDrivableActor/") and not raw.startswith("CurrentDrivableActor."):
        tail = raw[len("CurrentDrivableActor/") :]
        candidates.append(f"CurrentDrivableActor.{tail.replace('/', '.')}")

    if raw.startswith("DriverInput/0/"):
        candidates.append("DriverInput." + raw[len("DriverInput/0/") :])

    # dedupe preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            ordered.append(path)

    expanded: list[str] = []
    for path in ordered:
        expanded.append(path)
        if "CurrentFormation/0.Function.HUD_" in path:
            expanded.append(path.replace("CurrentFormation/0.Function.", "CurrentDrivableActor.Function."))
    seen.clear()
    ordered = []
    for path in expanded:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def unwrap_http_scalar(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "Value"):
            if key in value:
                inner = value[key]
                if isinstance(inner, (int, float, str, bool)) or inner is None:
                    return inner
                if isinstance(inner, dict):
                    return unwrap_http_scalar(inner)
        if len(value) == 1:
            return unwrap_http_scalar(next(iter(value.values())))
    return value


def _float_close(a: float, b: float, rtol: float = 1e-3, atol: float = 1e-5) -> bool:
    if math.isnan(a) or math.isnan(b):
        return False
    if abs(a) >= SENTINEL * 0.9 or abs(b) >= SENTINEL * 0.9:
        return abs(a - b) < 1.0
    return math.isclose(a, b, rel_tol=rtol, abs_tol=atol)


def compare_values(expected: Any, actual: Any, rtol: float = 1e-3) -> MatchKind:
    if actual is None:
        return "no_data"
    if isinstance(expected, dict) and len(expected) == 1 and not isinstance(actual, dict):
        expected = next(iter(expected.values()))
    if type(expected) is type(actual) and isinstance(expected, (str, bool, type(None))):
        return "exact" if expected == actual else "mismatch"
    if isinstance(expected, dict) and isinstance(actual, dict):
        keys = set(expected.keys())
        if keys != set(actual.keys()):
            return "mismatch"
        kinds = [compare_values(expected[k], actual[k], rtol=rtol) for k in sorted(keys)]
        if all(k == "exact" for k in kinds):
            return "exact"
        if all(k in ("exact", "fuzzy") for k in kinds):
            return "fuzzy"
        return "mismatch"
    try:
        exp_f = float(expected)  # type: ignore[arg-type]
        act_f = float(unwrap_http_scalar(actual))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "exact" if expected == actual else "mismatch"
    if _float_close(exp_f, act_f, rtol=rtol):
        return "exact" if exp_f == act_f else "fuzzy"
    return "mismatch"


def collect_http_guesses(session_dir: Path) -> list[GuessRow]:
    rows: list[GuessRow] = []
    for name in EXPORT_FILES:
        path = session_dir / name
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        guess = data.get("http_guess") or {}
        if not isinstance(guess, dict):
            continue
        for key, value in sorted(guess.items()):
            rows.append(GuessRow(path=str(key), expected=value, source=name))
    return rows


def fetch_http_value(client: TswApiClient, lab_path: str) -> tuple[Any, Optional[str], Optional[str]]:
    last_err: Optional[str] = None
    for api_path in normalize_api_path_candidates(lab_path):
        values = client.get_node(api_path)
        if values is None:
            last_err = f"GET failed: {api_path}"
            continue
        if isinstance(values, dict) and len(values) == 1 and lab_path.endswith(tuple(values.keys())):
            return next(iter(values.values())), None, api_path
        return values, None, api_path
    return None, last_err or "no candidate path worked", None


def default_formation_probe_defs() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for node, field, _kind in FORMATION_PROBE_SPECS:
        rows.append(
            {
                "path": f"CurrentFormation/0/Simulation/{node}.{field}",
                "scope": "formation",
                "node": node,
                "field": field,
            }
        )
        rows.append(
            {
                "path": f"CurrentDrivableActor/Simulation/{node}.{field}",
                "scope": "drivable",
                "node": node,
                "field": field,
            }
        )
    return rows


def collect_formation_probe_defs(session_dir: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    formation_path = session_dir / "formation.json"
    formation_meta: dict[str, Any] = {}
    if formation_path.is_file():
        formation_meta = json.loads(formation_path.read_text(encoding="utf-8"))
        probes = formation_meta.get("http_probe")
        if isinstance(probes, list) and probes:
            cleaned: list[dict[str, str]] = []
            for item in probes:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path") or "").strip()
                if not path:
                    continue
                cleaned.append(
                    {
                        "path": path,
                        "scope": str(item.get("scope") or ""),
                        "node": str(item.get("node") or ""),
                        "field": str(item.get("field") or ""),
                    }
                )
            if cleaned:
                return cleaned, formation_meta
    return default_formation_probe_defs(), formation_meta


def attach_lua_probe_context(rows: list[FormationProbeRow], formation_meta: dict[str, Any]) -> None:
    lua_probe = formation_meta.get("lua", {}).get("lua_probe")
    if not isinstance(lua_probe, dict):
        return
    for row in rows:
        node_info = lua_probe.get(row.node)
        if not isinstance(node_info, dict):
            continue
        row.lua_index_ok = bool(node_info.get("index_ok"))
        fields = node_info.get("fields")
        row.lua_fields = fields if isinstance(fields, dict) else {}


def fetch_formation_snapshot(
    session_dir: Path,
    client: Optional[TswApiClient] = None,
) -> FormationSnapshot:
    session_id = session_dir.name
    session_json = session_dir / "session.json"
    if session_json.is_file():
        meta = json.loads(session_json.read_text(encoding="utf-8"))
        session_id = str(meta.get("session_id") or session_id)

    probe_defs, formation_meta = collect_formation_probe_defs(session_dir)
    snapshot = FormationSnapshot(
        session_id=session_id,
        build=str(formation_meta.get("build") or ""),
    )

    rows: list[FormationProbeRow] = []
    for item in probe_defs:
        rows.append(
            FormationProbeRow(
                path=item["path"],
                scope=item.get("scope") or "",
                node=item.get("node") or "",
                field=item.get("field") or "",
            )
        )
    attach_lua_probe_context(rows, formation_meta)
    snapshot.rows = rows

    if client is None:
        for row in rows:
            row.status = "skipped"
            row.note = "no HTTP client"
        return snapshot

    snapshot.http_alive = client.probe()
    if not snapshot.http_alive:
        for row in rows:
            row.status = "skipped"
            row.note = "HTTPAPI not reachable"
        return snapshot

    for row in rows:
        actual, err, api_path = fetch_http_value(client, row.path)
        row.api_path = api_path
        if err:
            row.status = "http_error"
            row.note = err
            continue
        if actual is None:
            row.status = "no_data"
            continue
        row.actual = actual
        row.status = "ok"

    return snapshot


def formation_lua_diagnosis(snapshot: FormationSnapshot) -> list[str]:
    lines: list[str] = []
    ok = snapshot.ok_paths()
    if not ok:
        lines.append("- HTTP no devolvió ningún nodo Simulation legible en esta sesión.")
        return lines

    indexed = [r for r in snapshot.rows if r.lua_index_ok is True]
    readable_lua = [
        r
        for r in snapshot.rows
        if r.lua_fields and any(v is not None for v in r.lua_fields.values())
    ]
    if ok and not indexed:
        lines.append(
            "- **HTTP sí, Lua no:** los valores existen en HTTPAPI pero `sim[node]` no devuelve "
            "objeto en UE4SS (`index_ok=false`). No es un problema de nombre de campo — el binding "
            "Lua no expone el subgrafo Simulation."
        )
    elif ok and indexed and not readable_lua:
        lines.append(
            "- **Índice Lua parcial:** `sim[node]` existe pero ningún campo numérico leíble; "
            "probar `reflect_shallow` sobre `actor.Simulation` o ProcessEvent."
        )
    elif readable_lua:
        lines.append(
            "- **Lua legible:** al menos un nodo/campo leído en Lua; revisar por qué `formation.lua` "
            "no lo capturó en `simulation{}`."
        )

    best = snapshot.best_pressure_bar()
    if best:
        path, bar = best
        lines.append(f"- Presión cilindro HTTP: **{bar:.3g} BAR** vía `{path}`")
    return lines


def render_formation_report(snapshot: FormationSnapshot) -> str:
    ok_count = len(snapshot.ok_paths())
    lines = [
        f"# Formation HTTP — {snapshot.session_id}",
        "",
        f"- Build: **{snapshot.build or '—'}**",
        f"- HTTP alive: **{snapshot.http_alive}**",
        f"- Probes: **{len(snapshot.rows)}** · OK: **{ok_count}**",
        "",
        "## Diagnóstico Lua vs HTTP",
        "",
    ]
    lines.extend(formation_lua_diagnosis(snapshot) or ["- Sin datos para diagnosticar."])
    lines.extend(
        [
            "",
            "## Detail",
            "",
            "| Status | Scope | Node | Field | Lua index | HTTP value | API path |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in snapshot.rows:
        if row.status != "ok" and row.lua_index_ok is not True:
            continue
        val = row.actual
        if isinstance(val, dict):
            val_s = json.dumps(val, ensure_ascii=False)
        elif val is None:
            val_s = "—"
        elif isinstance(val, (int, float)):
            val_s = f"{val:.6g}"
        else:
            val_s = json.dumps(val, ensure_ascii=False)
        if len(val_s) > 40:
            val_s = val_s[:37] + "..."
        lua_ix = "—" if row.lua_index_ok is None else ("yes" if row.lua_index_ok else "no")
        api = row.api_path or row.note or "—"
        lines.append(
            f"| {row.status} | {row.scope} | `{row.node}` | `{row.field}` | {lua_ix} | {val_s} | `{api}` |"
        )
    lines.append("")
    return "\n".join(lines)


def write_formation_snapshot(session_dir: Path, snapshot: FormationSnapshot) -> tuple[Path, Path]:
    json_path = session_dir / "formation_http.json"
    report_path = session_dir / "formation_report.md"

    payload = {
        "schema": "tsw6-lab-export/formation-http/1",
        "session_id": snapshot.session_id,
        "build": snapshot.build,
        "http_alive": snapshot.http_alive,
        "probe_count": len(snapshot.rows),
        "ok_count": len(snapshot.ok_paths()),
        "diagnosis": formation_lua_diagnosis(snapshot),
        "rows": [
            {
                "path": row.path,
                "scope": row.scope,
                "node": row.node,
                "field": row.field,
                "status": row.status,
                "api_path": row.api_path,
                "actual": row.actual,
                "lua_index_ok": row.lua_index_ok,
                "lua_fields": row.lua_fields,
                "note": row.note,
            }
            for row in snapshot.rows
        ],
    }
    best = snapshot.best_pressure_bar()
    if best:
        payload["brake_cyl_bar_http"] = {"path": best[0], "value": best[1]}

    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_path.write_text(render_formation_report(snapshot), encoding="utf-8")
    return json_path, report_path


def correlate_session(
    session_dir: Path,
    client: Optional[TswApiClient] = None,
    *,
    hud_only: bool = False,
    rtol: float = 1e-3,
) -> CorrelationSummary:
    session_id = session_dir.name
    session_json = session_dir / "session.json"
    if session_json.is_file():
        meta = json.loads(session_json.read_text(encoding="utf-8"))
        session_id = str(meta.get("session_id") or session_id)

    rows = collect_http_guesses(session_dir)
    if hud_only:
        rows = [r for r in rows if r.source == "hud_batch.json"]

    summary = CorrelationSummary(rows=rows, session_id=session_id)

    if client is None:
        for row in rows:
            row.match = "skipped"
            row.note = "no HTTP client"
        return summary

    summary.http_alive = client.probe()
    if not summary.http_alive:
        for row in rows:
            row.match = "skipped"
            row.note = "HTTPAPI not reachable"
        return summary

    for row in rows:
        actual, err, api_path = fetch_http_value(client, row.path)
        row.api_path = api_path
        if err:
            row.match = "http_error"
            row.note = err
            continue
        row.actual = actual
        row.match = compare_values(row.expected, actual, rtol=rtol)
        if row.match == "mismatch" and isinstance(row.expected, (int, float)):
            unwrapped = unwrap_http_scalar(actual)
            if isinstance(unwrapped, (int, float)):
                row.note = f"http scalar={unwrapped}"

    return summary


def render_report(summary: CorrelationSummary) -> str:
    counts = summary.counts()
    lines = [
        f"# Correlation report — {summary.session_id}",
        "",
        f"- HTTP alive: **{summary.http_alive}**",
        f"- Rows: **{len(summary.rows)}**",
    ]
    hud_ratio = summary.hud_exact_ratio()
    if hud_ratio is not None:
        lines.append(f"- HUD exact match: **{hud_ratio * 100:.1f}%**")
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    for kind in ("exact", "fuzzy", "mismatch", "http_error", "no_data", "skipped"):
        if counts.get(kind):
            lines.append(f"- `{kind}`: {counts[kind]}")
    lines.append("")
    lines.append("## Detail")
    lines.append("")
    lines.append("| Match | Source | Lab path | API path | Expected | Actual |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for row in summary.rows:
        exp = json.dumps(row.expected, ensure_ascii=False) if not isinstance(row.expected, (int, float)) else f"{row.expected:.6g}"
        act = row.actual
        if isinstance(act, dict):
            act_s = json.dumps(act, ensure_ascii=False)
        elif act is None:
            act_s = "—"
        elif isinstance(act, (int, float)):
            act_s = f"{act:.6g}"
        else:
            act_s = json.dumps(act, ensure_ascii=False)
        if len(exp) > 48:
            exp = exp[:45] + "..."
        if len(act_s) > 48:
            act_s = act_s[:45] + "..."
        api = row.api_path or (row.note[:32] if row.note else "—")
        lines.append(
            f"| {row.match} | {row.source} | `{row.path}` | `{api}` | {exp} | {act_s} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path, help="exports/<session>/ folder")
    parser.add_argument("--hud-only", action="store_true", help="Only hud_batch.json paths")
    parser.add_argument(
        "--min-exact",
        type=float,
        default=None,
        help="Fail if HUD exact ratio below this (0–1), implies --hud-only",
    )
    parser.add_argument(
        "--formation",
        action="store_true",
        help="Fetch Simulation nodes via HTTP; write formation_http.json",
    )
    parser.add_argument(
        "--dry-list",
        action="store_true",
        help="List http_guess paths only; no HTTP",
    )
    parser.add_argument("--rtol", type=float, default=1e-3, help="Relative tolerance floats")
    args = parser.parse_args()

    session_dir = args.session_dir.resolve()
    if not session_dir.is_dir():
        print(f"ERROR: not a directory: {session_dir}", file=sys.stderr)
        return 1

    if args.dry_list:
        rows = collect_http_guesses(session_dir)
        for row in rows:
            cands = normalize_api_path_candidates(row.path)
            print(f"{row.source}\t{row.path}\t->\t{cands[0]}")
        print(f"\n{len(rows)} paths")
        if args.formation:
            probe_defs, _ = collect_formation_probe_defs(session_dir)
            print(f"\n{len(probe_defs)} formation probes")
            for item in probe_defs[:8]:
                print(f"formation\t{item['path']}")
            if len(probe_defs) > 8:
                print(f"... +{len(probe_defs) - 8} more")
        return 0

    if args.formation:
        client = client_from_key_file()
        if client is None:
            print("WARN: CommAPIKey.txt not found — formation rows will be skipped", file=sys.stderr)
        snapshot = fetch_formation_snapshot(session_dir, client)
        json_path, report_path = write_formation_snapshot(session_dir, snapshot)
        print(render_formation_report(snapshot))
        print(f"\nWrote {json_path}")
        print(f"Wrote {report_path}")
        if client is not None and not snapshot.http_alive:
            return 3
        return 0

    hud_only = args.hud_only or args.min_exact is not None
    client = client_from_key_file()
    if client is None:
        print("WARN: CommAPIKey.txt not found — report will mark skipped", file=sys.stderr)

    summary = correlate_session(
        session_dir,
        client,
        hud_only=hud_only,
        rtol=args.rtol,
    )
    report = render_report(summary)
    out_path = session_dir / "correlation_report.md"
    out_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWrote {out_path}")

    if args.min_exact is not None:
        ratio = summary.hud_exact_ratio()
        if ratio is None:
            print("ERROR: no HUD rows to score", file=sys.stderr)
            return 1
        if ratio < args.min_exact:
            print(
                f"FAIL: HUD exact {ratio * 100:.1f}% < {args.min_exact * 100:.1f}%",
                file=sys.stderr,
            )
            return 2
        print(f"OK: HUD exact {ratio * 100:.1f}% >= {args.min_exact * 100:.1f}%")

    if not summary.http_alive and client is not None:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
