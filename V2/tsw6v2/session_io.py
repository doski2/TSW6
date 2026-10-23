"""Lectura de JSONL de sesión: una sola implementación, con política de errores explícita."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def iter_session_rows(path: Path, *, strict: bool) -> Iterator[dict[str, Any]]:
    """Filas JSON del fichero, sin líneas en blanco.

    ``strict=True``: una línea rota lanza ``ValueError`` (informes, que no deben mentir).
    ``strict=False``: se ignora la línea rota o no UTF-8 (análisis de logs que pueden estar
    truncados al cerrar el juego).
    """
    errors = "strict" if strict else "replace"
    with path.open(encoding="utf-8", errors=errors) as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                if strict:
                    raise
                continue
            if isinstance(row, dict):
                yield row
