"""
TSW6 proyecto V2 — carpeta raíz: ``V2/``.

Código nuevo. Contrato D2 en ``tsw6v2.bridge`` y ``channel``.
"""

from tsw6v2.constants import B1_NOTCH, NEUTRAL_NOTCH
from tsw6v2.diagnostic import run_ipc_brake_test
from tsw6v2.ipc import drive_to_notch, ipc_steps_needed
from tsw6v2.loop import AgentLoop, AgentSnapshot

__all__ = [
    "AgentLoop",
    "AgentSnapshot",
    "B1_NOTCH",
    "NEUTRAL_NOTCH",
    "drive_to_notch",
    "ipc_steps_needed",
    "run_ipc_brake_test",
]
