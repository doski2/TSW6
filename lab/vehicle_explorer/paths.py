"""Rutas lab_exports (repo o TSW6_LAB_DIR / Documents\\TSW6\\lab_root.txt)."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    return _REPO_ROOT


def lab_exports_dir() -> Path:
    env = os.environ.get("TSW6_LAB_DIR")
    if env:
        base = Path(env)
        if (base / "exports").is_dir():
            return base / "exports"
        if base.name == "exports" and base.is_dir():
            return base
        return base / "exports"
    doc = Path.home() / "Documents" / "TSW6" / "lab_root.txt"
    if doc.is_file():
        text = doc.read_text(encoding="utf-8").strip()
        if text:
            root = Path(text)
            exp = root / "exports"
            if exp.is_dir():
                return exp
    default = _REPO_ROOT / "data" / "lab_exports" / "exports"
    default.mkdir(parents=True, exist_ok=True)
    return default
