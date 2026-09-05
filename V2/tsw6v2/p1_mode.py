"""Modos P1 sesión (cartel, estación, señal) — un solo contrato de trace."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tsw6v2.loop import AgentLoop

P1_MODES = frozenset({"console", "limit", "station", "signal", "p1"})


def resolve_p1_mode(*, mode: str | None, limit_brake: bool) -> str:
    if mode:
        m = mode.strip().lower()
        if m not in P1_MODES:
            raise ValueError(f"modo P1 desconocido: {mode!r} (use: {', '.join(sorted(P1_MODES - {'console'}))})")
        return m
    if limit_brake:
        return "limit"
    return "console"


def apply_p1_mode(loop: AgentLoop, mode: str) -> list[str]:
    """Activa flags del bucle; avisos si el modo aún no tiene P1."""
    warnings: list[str] = []
    loop.limit_brake_enabled = mode in ("limit", "p1")
    # Pasos futuros: descomentar al cablear estación / señal en loop.
    # loop.station_brake_enabled = mode in ("station", "p1")
    # loop.signal_brake_enabled = mode in ("signal", "p1")
    if mode in ("station", "p1"):
        warnings.append("P1 estación: no implementado (paso 7) — trace + probe activos")
    if mode in ("signal", "p1"):
        warnings.append("P1 señal: no implementado (paso 4-5) — trace + probe activos")
    return warnings


def session_trace_mode(mode: str) -> str:
    """Etiqueta en JSONL sesión."""
    return mode if mode != "console" else "probe-only"
