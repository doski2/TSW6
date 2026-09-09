"""Modos P1 sesión (cartel, estación, señal) — un solo contrato de trace."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tsw6v2.loop import AgentLoop

P1_MODES = frozenset({"console", "limit", "station", "signal", "p1"})

# GUI producto: cartel + andén van juntos (la consola mantiene limit/station para validar por separado).
GUI_P1_MODES: tuple[str, ...] = ("off", "p1")


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
    loop.limit_brake_enabled = mode in ("limit", "station", "p1")
    loop.station_brake_enabled = mode in ("station", "p1")
    # loop.signal_brake_enabled = mode in ("signal", "p1")
    if mode in ("station", "p1"):
        warnings.append(f"P1 estación: distancia vía {loop.station_planning_channel}")
    if mode == "signal":
        warnings.append("P1 señal: no implementado (paso 4-5) — trace + probe activos")
    return warnings


def session_trace_mode(mode: str) -> str:
    """Etiqueta en JSONL sesión."""
    if mode == "console":
        return "probe-only"
    if mode == "p1":
        return "station"
    return mode


def resolve_gui_p1_mode(mode: str) -> str:
    """Modo visor GUI: ``off`` | ``p1``. Acepta alias ``limit``/``station`` → ``p1``."""
    m = (mode or "off").strip().lower()
    if m in ("console", "probe", "off", ""):
        return "off"
    if m in ("limit", "station", "p1", "signal"):
        return "p1"
    return "p1"


def gui_mode_to_loop_mode(gui_mode: str) -> str:
    """Mapea modo GUI al contrato ``apply_p1_mode`` (trace JSONL = ``station``)."""
    if resolve_gui_p1_mode(gui_mode) == "off":
        return "console"
    return "station"
