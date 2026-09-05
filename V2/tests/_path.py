"""Side-effect: repo root + V2/ en sys.path (Run Python File y pytest)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_V2 = _ROOT / "V2"
for _p in (str(_ROOT), str(_V2)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _pause_if_explorer_launch() -> None:
    """Mantener consola abierta al doble clic en Explorer (no en Cursor/VS Code)."""
    if sys.platform != "win32":
        return
    if os.environ.get("TERM_PROGRAM") == "vscode":
        return
    if not sys.stdin.isatty():
        return
    try:
        input("\nEnter para cerrar...")
    except EOFError:
        pass


def run_self_tests(*, verbose: bool = True) -> int:
    """Ejecuta pytest sobre el archivo de test que llama a esta función."""
    import inspect

    import pytest

    caller = inspect.stack()[1].filename
    args: list[str] = [caller]
    if verbose:
        args.append("-v")
    code = int(pytest.main(args))
    _pause_if_explorer_launch()
    return code
