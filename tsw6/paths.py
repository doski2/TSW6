"""Rutas del proyecto TSW6 (raíz del repositorio)."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
HUD_DB_FILENAME = "tsw_hud.db"


def project_db_paths() -> list[Path]:
    """Ubicaciones conocidas de ``tsw_hud.db``."""
    root = PROJECT_ROOT
    return [
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
