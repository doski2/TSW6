"""Expone ``_tick_to_snap`` de ``scripts/replay_jsonl.py`` para los tests de replay."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from tsw6v2.bridge.getdata import ProbeSnapshot

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay_jsonl.py"
_spec = importlib.util.spec_from_file_location("replay_jsonl", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


def tick_to_snap(tick: dict[str, Any]) -> ProbeSnapshot:
    """Fila ``tick`` del JSONL de sesión → ``ProbeSnapshot`` (misma conversión que el replay)."""
    return _module._tick_to_snap(tick)
