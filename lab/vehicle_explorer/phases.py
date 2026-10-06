"""Checklist por fases (PLAN_API_EXPLORER L0) — progreso por carpeta de sesión."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# Archivos que el explorer puede escribir (múltiples F5 con nombre distinto = copia manual)
CORE_FILES = frozenset(
    {
        "session.json",
        "hud_batch.json",
        "controls.json",
        "driver_aid.json",
    }
)

OPTIONAL_FILES = frozenset(
    {
        "formation.json",
        "formation_http.json",
        "reflect_shallow.json",
        "correlate_tick.json",
        "correlation_report.md",
        "formation_report.md",
    }
)

RAILBRIDGE_GLOB = "*.json"


@dataclass(frozen=True)
class LabPhase:
    id: str
    title: str
    in_game: str
    files: tuple[str, ...] = ()
    dirs: tuple[str, ...] = ()
    notes: str = ""

    def done(self, session_dir: Path) -> bool:
        for name in self.files:
            if not (session_dir / name).is_file():
                return False
        for d in self.dirs:
            sub = session_dir / d
            if not sub.is_dir():
                return False
            if d == "railbridge":
                if not any(sub.glob(RAILBRIDGE_GLOB)):
                    return False
        return True

    def assistant_done(self, session_dir: Path) -> bool:
        """Progreso L0 para GUI (fases opcionales + .lab_skip_<id>)."""
        if (session_dir / f".lab_skip_{self.id}").is_file():
            return True
        if self.id == "l0_4b":
            return any(session_dir.glob("driver_aid_signal*.json")) or any(
                session_dir.glob("driver_aid_*signal*.json")
            )
        if self.id == "l0_6g":
            return len(list(session_dir.glob("hud_batch_*.json"))) >= 1
        if self.id in ("package", "probe"):
            return False
        return self.done(session_dir)


# Orden de ejecución en cabina (usuario marca copiando hud_batch si hace varias F5)
PHASES: tuple[LabPhase, ...] = (
    LabPhase(
        "prep",
        "Preparación",
        "install_ue4ss_explorer.bat · escenario GCT-MNR · M3a enganchado · notas_sesion.md",
        files=("notas_sesion.md",),
        notes="Ruta, consist, variante A/B, build probe si aplica.",
    ),
    LabPhase(
        "l0_2_3",
        "HUD + mandos",
        "F5 (parado reposo) → F6 (controls)",
        files=("hud_batch.json", "controls.json"),
        notes="Comprobar layout_hint / MasterController en F6.",
    ),
    LabPhase(
        "l0_4",
        "DriverAid",
        "F7 (parado, límite y estación visibles)",
        files=("driver_aid.json",),
    ),
    LabPhase(
        "l0_4b",
        "Señales (catálogo)",
        "F7 extra: verde → restrict/ámbar → stop (US MNR; no asumir UK)",
        files=(),
        notes="Opcional: copiar driver_aid como driver_aid_signal_stop.json",
    ),
    LabPhase(
        "l0_6g",
        "Aire / MC",
        "F5 × N: neutro, B1, B2, B3, tracción · renombrar hud_batch_*.json",
        files=(),
        notes="Ver PLAN_API_EXPLORER § L0.6g M3a; Shift+F5 para formation.",
    ),
    LabPhase(
        "l0_6",
        "Formation",
        "Shift+F5 · con -HTTPAPI: api_correlator.py --formation <sesión>",
        files=("formation.json",),
        notes="formation_http.json tras correlator en PC.",
    ),
    LabPhase(
        "railbridge",
        "Catálogo HTTP",
        "Copiar dumps RailBridge a esta carpeta (mismo día que F5–F7)",
        dirs=("railbridge",),
        notes="CurrentDrivableActor, DriverInput, Formation, Player…",
    ),
    LabPhase(
        "package",
        "Paquete G-B",
        "vehicles_json_from_lab.py · build_m3a_profile_from_exports.py (M3a)",
        files=(),
        notes="Salida data/vehicles/<id>.json — revisar diff en GUI.",
    ),
    LabPhase(
        "probe",
        "Cruce probe",
        "run_p1_session + compare_lab_vs_probe.py",
        files=(),
        notes="GetData vs hud_batch; mc_input en M3a.",
    ),
)


def list_present_files(session_dir: Path) -> set[str]:
    if not session_dir.is_dir():
        return set()
    return {p.name for p in session_dir.iterdir() if p.is_file()}


def phase_report(session_dir: Path, for_assistant: bool = False) -> list[tuple[LabPhase, bool]]:
    if for_assistant:
        return [(ph, ph.assistant_done(session_dir)) for ph in PHASES]
    return [(ph, ph.done(session_dir)) for ph in PHASES]


def first_pending_phase(session_dir: Path) -> Optional[LabPhase]:
    for ph in PHASES:
        if not ph.assistant_done(session_dir):
            return ph
    return None


def mark_phase_skipped(session_dir: Path, phase_id: str) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    flag = session_dir / f".lab_skip_{phase_id}"
    flag.write_text("skipped\n", encoding="utf-8")
    return flag


def prepare_pc_for_phase(session_dir: Path, phase: LabPhase) -> list[str]:
    """Solo filesystem en repo; no toca el juego."""
    from .paths import repo_root

    lines: list[str] = []
    session_dir.mkdir(parents=True, exist_ok=True)
    if phase.id == "prep":
        tpl = repo_root() / "data" / "lab_exports" / "templates" / "notas_sesion.md"
        dest = session_dir / "notas_sesion.md"
        if not dest.is_file() and tpl.is_file():
            text = tpl.read_text(encoding="utf-8")
            text = text.replace("(carpeta timestamp, p. ej. 20261005T…)", session_dir.name)
            dest.write_text(text, encoding="utf-8")
            lines.append(f"Creado {dest.name}")
        elif dest.is_file():
            lines.append(f"Ya existe {dest.name}")
        rb = session_dir / "railbridge"
        rb.mkdir(exist_ok=True)
        lines.append("Carpeta railbridge/ lista")
        return lines
    if phase.id == "railbridge":
        (session_dir / "railbridge").mkdir(exist_ok=True)
        lines.append("Carpeta railbridge/ lista (usa copiar dumps o botón en asistente)")
        return lines
    lines.append(f"Fase {phase.id}: acción principal en cabina ({phase.in_game})")
    return lines


def format_phase_report(session_dir: Path, vehicle_class: Optional[str] = None) -> str:
    lines = [
        "Fases L0 (ejecuta en orden; marca archivos en la carpeta de sesión)",
        f"Carpeta: {session_dir}",
        "",
    ]
    if vehicle_class:
        lines.append(f"vehicle_class: {vehicle_class}")
        if "M3a" in vehicle_class or "NYH" in vehicle_class:
            lines.append("Tren MC — priorizar L0.6g + railbridge + puertas en F6/F7")
        lines.append("")
    done_n = 0
    for ph, ok in phase_report(session_dir, for_assistant=True):
        mark = "x" if ok else " "
        done_n += int(ok)
        lines.append(f"  [{mark}] {ph.id}: {ph.title}")
        lines.append(f"      En juego: {ph.in_game}")
        if ph.files:
            have = [f for f in ph.files if (session_dir / f).is_file()]
            miss = [f for f in ph.files if f not in have]
            if have:
                lines.append(f"      OK: {', '.join(have)}")
            if miss:
                lines.append(f"      Falta: {', '.join(miss)}")
        if ph.dirs:
            for d in ph.dirs:
                sub = session_dir / d
                n = len(list(sub.glob(RAILBRIDGE_GLOB))) if sub.is_dir() else 0
                lines.append(f"      {d}/: {n} json" if n else f"      {d}/: (vacío)")
        if ph.notes:
            lines.append(f"      → {ph.notes}")
        lines.append("")
    lines.append(f"Progreso fases automáticas: {done_n}/{len(PHASES)}")
    present = list_present_files(session_dir)
    core_ok = CORE_FILES.issubset(present)
    lines.append(f"Nucleo L0 (session+hud+controls+driver_aid): {'OK' if core_ok else 'pendiente'}")
    opt = sorted(present & OPTIONAL_FILES)
    if opt:
        lines.append(f"Opcionales presentes: {', '.join(opt)}")
    return "\n".join(lines)
