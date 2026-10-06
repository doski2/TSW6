"""Acciones PC del asistente L0 (correlator, G-B, prep carpeta, RailBridge)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .paths import repo_root
from .phases import LabPhase, PHASES, first_pending_phase, mark_phase_skipped, prepare_pc_for_phase

_PYTHON = sys.executable


def suggest_vehicle_id(vehicle_class: Optional[str]) -> str:
    text = (vehicle_class or "").upper()
    if "M3A" in text or "NYH" in text or "M7A" in text:
        return "m3a_mnr"
    if "323" in text:
        return "class_323"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", (vehicle_class or "").strip()).strip("_").lower()
    return slug or "unknown"


def railbridge_cache_dir() -> Optional[Path]:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "RailBridge" / "cache" / "api-dumps"
    return base if base.is_dir() else None


def copy_latest_railbridge_dumps(session_dir: Path, limit_per_kind: int = 1) -> list[str]:
    """Copia el JSON más reciente de cada prefijo RailBridge a sesión/railbridge/."""
    cache = railbridge_cache_dir()
    dest = session_dir / "railbridge"
    dest.mkdir(parents=True, exist_ok=True)
    if cache is None:
        return ["RailBridge cache no encontrada (exporta desde la app a api-dumps)."]
    prefix_re = re.compile(r"^tsw-api-export-(.+?)-(\d{8}T\d{6}Z)\.json$", re.I)
    by_kind: dict[str, Path] = {}
    for path in cache.glob("tsw-api-export-*.json"):
        m = prefix_re.match(path.name)
        if not m:
            continue
        kind = m.group(1)
        prev = by_kind.get(kind)
        if prev is None or path.stat().st_mtime > prev.stat().st_mtime:
            by_kind[kind] = path
    if not by_kind:
        return [f"Sin dumps en {cache}"]
    lines: list[str] = []
    for kind, src in sorted(by_kind.items()):
        target = dest / src.name
        shutil.copy2(src, target)
        lines.append(f"Copiado {src.name}")
    return lines


def run_command(
    args: list[str],
    cwd: Optional[Path] = None,
    timeout_s: int = 120,
) -> tuple[int, str]:
    root = repo_root()
    work = cwd or root
    try:
        proc = subprocess.run(
            args,
            cwd=str(work),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return 1, f"Timeout ({timeout_s}s): {' '.join(args)}"
    except OSError as exc:
        return 1, str(exc)
    out = (proc.stdout or "") + (proc.stderr or "")
    if not out.strip():
        out = f"exit code {proc.returncode}"
    return proc.returncode, out.strip()


def run_correlator(session_dir: Path, formation: bool = True) -> tuple[int, str]:
    script = repo_root() / "scripts" / "tools" / "api_correlator.py"
    args = [_PYTHON, str(script), str(session_dir.resolve())]
    if formation:
        args.append("--formation")
    return run_command(args, timeout_s=90)


def run_vehicles_json(session_dir: Path, vehicle_id: str) -> tuple[int, str]:
    script = repo_root() / "scripts" / "tools" / "vehicles_json_from_lab.py"
    args = [
        _PYTHON,
        str(script),
        str(session_dir.resolve()),
        "--vehicle-id",
        vehicle_id,
    ]
    return run_command(args)


def assistant_summary(session_dir: Path, vehicle_class: Optional[str] = None) -> str:
    ph = first_pending_phase(session_dir)
    if ph is None:
        return "L0 completo (o todo marcado). Revisa package/probe manualmente."
    lines = [
        f"Fase actual: {ph.id} — {ph.title}",
        "",
        "Tu turno en cabina:",
        f"  {ph.in_game}",
    ]
    if ph.notes:
        lines.extend(["", f"Nota: {ph.notes}"])
    pc = _pc_hint(ph, session_dir, vehicle_class)
    if pc:
        lines.extend(["", "En PC (botones abajo):", f"  {pc}"])
    return "\n".join(lines)


def _pc_hint(ph: LabPhase, session_dir: Path, vehicle_class: Optional[str]) -> str:
    if ph.id == "prep":
        return "Preparar PC: notas + carpeta railbridge/"
    if ph.id == "l0_6":
        return "Correlator (--formation) con TSW -HTTPAPI"
    if ph.id == "railbridge":
        return "Preparar PC: copiar dumps RailBridge a railbridge/"
    if ph.id == "package":
        vid = suggest_vehicle_id(vehicle_class)
        return f"Generar G-B → data/vehicles/{vid}.json"
    if ph.id == "probe":
        return "run_p1_session + compare_lab_vs_probe.py (manual)"
    return ""


def do_prepare_pc(
    session_dir: Path,
    phase: Optional[LabPhase] = None,
    vehicle_class: Optional[str] = None,
) -> list[str]:
    ph = phase or first_pending_phase(session_dir)
    if ph is None:
        return ["No hay fase pendiente."]
    lines = list(prepare_pc_for_phase(session_dir, ph))
    if ph.id == "railbridge":
        lines.extend(copy_latest_railbridge_dumps(session_dir))
    return lines
