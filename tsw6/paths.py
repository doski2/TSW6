"""Rutas del proyecto TSW6 (raíz del repositorio)."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
HUD_DB_FILENAME = "tsw_hud.db"

# BD completa tras extracción en hud.exe (todos los DLCs del juego).
HUD_RELEASE_DB = (
    Path.home()
    / "Desktop"
    / "investigacion tsw 6"
    / "tsw_projects-main"
    / "tsw_projects-main"
    / "hud"
    / "src-tauri"
    / "target"
    / "release"
    / "resources"
    / "db"
    / HUD_DB_FILENAME
)


def project_db_paths() -> list[Path]:
    """Ubicaciones conocidas de ``tsw_hud.db`` (prioridad ≈ ``default_hud_db_paths``)."""
    root = PROJECT_ROOT
    return [
        HUD_RELEASE_DB,
        root / HUD_DB_FILENAME,
        root / "data" / HUD_DB_FILENAME,
        Path.home()
        / "Desktop"
        / "investigacion tsw 6"
        / "tsw_projects-main"
        / "tsw_projects-main"
        / "hud"
        / "resources"
        / "db"
        / HUD_DB_FILENAME,
    ]
