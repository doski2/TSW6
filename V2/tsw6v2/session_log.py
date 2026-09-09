"""Grabación JSONL + replay HTML al cerrar sesión (consola o GUI)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tsw6v2.loop import AgentLoop, AgentSnapshot
from tsw6v2.session_report import (
    MIN_HTML_DURATION_S,
    MIN_HTML_TICKS,
    finalize_session_report,
    format_summary_line,
    session_ready_for_browser,
    summarize,
)
from tsw6v2.trace import JsonlTrace, session_meta


@dataclass(frozen=True)
class SessionCloseResult:
    jsonl_path: Path
    html_path: Optional[Path]
    summary: dict
    opened_browser: bool = False
    message: str = ""


class SessionRecorder:
    """Escribe ticks JSONL y genera replay HTML al ``finish()``."""

    def __init__(
        self,
        log_path: Path,
        *,
        trace_mode: str,
        route: str = "",
        profile: Optional[str] = None,
    ) -> None:
        self.log_path = log_path
        self.trace_mode = trace_mode
        self.route = route
        self.profile = profile
        self._trace: Optional[JsonlTrace] = None
        self._t0 = time.monotonic()

    def _ensure_trace(self) -> JsonlTrace:
        if self._trace is None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._trace = JsonlTrace(
                self.log_path,
                session_meta(
                    mode=self.trace_mode,
                    route=self.route,
                    profile=self.profile,
                ),
            )
        return self._trace

    def record(self, snap: AgentSnapshot) -> None:
        trace = self._ensure_trace()
        t_ms = (time.monotonic() - self._t0) * 1000.0
        trace.write_tick(snap, t_ms=t_ms, ipc_cmd_id=snap.ipc_cmd_id)

    def finish(
        self,
        *,
        open_html: bool = False,
        force_html: bool = False,
        generate_html: bool = True,
    ) -> SessionCloseResult:
        if self._trace is None:
            return SessionCloseResult(
                jsonl_path=self.log_path,
                html_path=None,
                summary={"error": "sin ticks"},
                message="Sesión sin datos (¿probe F7?).",
            )
        self._trace.close()
        if not generate_html:
            return SessionCloseResult(
                jsonl_path=self.log_path,
                html_path=None,
                summary={},
                message=f"JSONL -> {self.log_path.resolve()}",
            )
        data = summarize(self.log_path)
        html_out: Optional[Path] = None
        opened = False
        try:
            html_out = finalize_session_report(
                self.log_path,
                summary=data,
                force=force_html,
            )
        except (OSError, ValueError) as exc:
            return SessionCloseResult(
                jsonl_path=self.log_path,
                html_path=None,
                summary=data,
                message=f"No se pudo generar HTML: {exc}",
            )

        if html_out is not None and open_html:
            if session_ready_for_browser(data):
                os.startfile(str(html_out.resolve()))  # type: ignore[attr-defined]
                opened = True
            else:
                msg = (
                    "Replay guardado (sesión corta; conduce 1–2 min para gráfico útil).\n"
                    f"{html_out.resolve()}"
                )
                return SessionCloseResult(
                    jsonl_path=self.log_path,
                    html_path=html_out,
                    summary=data,
                    opened_browser=False,
                    message=msg,
                )

        if html_out is not None:
            msg = f"{format_summary_line(data)}\nreplay -> {html_out.resolve()}"
        else:
            msg = (
                f"{format_summary_line(data)}\n"
                f"JSONL -> {self.log_path.resolve()} "
                f"(HTML omitido: <{MIN_HTML_TICKS} ticks o <{MIN_HTML_DURATION_S}s)"
            )
        return SessionCloseResult(
            jsonl_path=self.log_path,
            html_path=html_out,
            summary=data,
            opened_browser=opened,
            message=msg,
        )


def session_profile_note(
    loop: AgentLoop,
    profile_path: Optional[Path],
) -> Optional[str]:
    """Ruta de perfil para metadatos JSONL (explícita o auto-cargada)."""
    if profile_path is not None:
        return str(profile_path)
    if loop.loaded_profile_path is not None:
        return str(loop.loaded_profile_path)
    return None


def make_session_recorder(
    log_path: Path,
    loop: AgentLoop,
    *,
    trace_mode: str,
    route: str = "",
    profile_path: Optional[Path] = None,
) -> SessionRecorder:
    """Crea ``SessionRecorder`` con perfil resuelto desde loop/CLI."""
    return SessionRecorder(
        log_path,
        trace_mode=trace_mode,
        route=route,
        profile=session_profile_note(loop, profile_path),
    )


def save_learner_if_dirty(loop: AgentLoop, profile_path: Optional[Path]) -> Optional[str]:
    """Persiste perfil si hubo aprendizaje; devuelve línea para consola."""
    save_path = profile_path or loop.loaded_profile_path
    active = loop.active_learner
    if save_path is None or not (active.brake_fill_n > 0 or active.decel_observe_n > 0):
        return None
    try:
        active.save_json(save_path)
    except OSError as exc:
        return f"AVISO: no se pudo guardar perfil: {exc}"
    parts: list[str] = []
    if active.brake_fill_n > 0:
        parts.append(f"fill={active.brake_fill_s:.2f}s")
    if active.decel_observe_n > 0:
        parts.append(f"decel_n={active.decel_observe_n}")
    return f"perfil -> {save_path.resolve()} ({', '.join(parts)})"
