"""Tiempo de juego derivado del ``seq`` del probe GetData."""

from __future__ import annotations

from typing import Optional

from tsw6v2.constants import PROBE_SEQ_MS


def probe_seq_delta_ms(
    last_seq: int | None,
    seq: int | None,
) -> Optional[float]:
    """Milisegundos de juego entre dos ``seq``; ``0`` si congelado o retroceso."""
    if seq is None or last_seq is None:
        return None
    delta = int(seq) - int(last_seq)
    if delta <= 0:
        return 0.0
    return delta * PROBE_SEQ_MS


def probe_seq_dt_s(last_seq: int | None, seq: int | None) -> Optional[float]:
    """Segundos de juego entre dos ``seq`` (~``PROBE_SEQ_MS`` por paso)."""
    delta_ms = probe_seq_delta_ms(last_seq, seq)
    if delta_ms is None:
        return None
    return delta_ms / 1000.0
