"""CLI — punto de entrada del proyecto V2."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from tsw6v2.constants import DEFAULT_LOOP_HZ
from tsw6v2.diagnostic import run_ipc_brake_test
from tsw6v2.gui import run_gui
from tsw6v2.learner import LearnerProfile
from tsw6v2.loop import AgentLoop
from tsw6v2.p1_mode import P1_MODES, apply_p1_mode, resolve_p1_mode, session_trace_mode
from tsw6v2.session_report import (
    finalize_session_report,
    format_summary_line,
    MIN_HTML_DURATION_S,
    MIN_HTML_TICKS,
    session_ready_for_browser,
    session_ready_for_html,
    summarize,
)
from tsw6v2.trace import JsonlTrace, default_log_path, format_investigate, session_meta


def run_console(
    *,
    hz: float = DEFAULT_LOOP_HZ,
    duration_s: Optional[float] = None,
    mode: str = "console",
    limit_brake: bool = False,
    profile_path: Optional[Path] = None,
    log_path: Optional[Path] = None,
    investigate: bool = False,
    route: str = "",
    session_html: bool = True,
    open_html: bool = False,
) -> int:
    try:
        p1_mode = resolve_p1_mode(mode=mode if mode != "console" else None, limit_brake=limit_brake)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    learner = LearnerProfile.from_json(profile_path) if profile_path else LearnerProfile()
    loop = AgentLoop(learner=learner)
    loop.post_ipc_sleep_s = 0.0
    for note in apply_p1_mode(loop, p1_mode):
        print(f"AVISO: {note}", file=sys.stderr)

    interval = 1.0 / max(1.0, hz)
    t0 = time.monotonic()
    use_investigate = investigate or p1_mode != "console"

    trace: Optional[JsonlTrace] = None
    if log_path is not None:
        trace = JsonlTrace(
            log_path,
            session_meta(
                mode=session_trace_mode(p1_mode),
                route=route,
                profile=str(profile_path) if profile_path else None,
            ),
        )
        print(f"log -> {log_path.resolve()}")

    print(f"TSW6 V2 agent - modo={p1_mode} - Ctrl+C para salir")
    try:
        while True:
            if duration_s is not None and (time.monotonic() - t0) >= duration_s:
                break
            snap = loop.step()
            t_ms = (time.monotonic() - t0) * 1000.0
            if use_investigate:
                print(format_investigate(snap))
            else:
                mph = f"{snap.speed_mph:.1f}" if snap.speed_mph is not None else "?"
                print(
                    f"tick={snap.tick} seq={snap.seq} mph={mph} "
                    f"lever={snap.lever_notch} target={snap.target_notch} "
                    f"ipc={snap.ipc_sent}"
                )
            if trace is not None:
                trace.write_tick(snap, t_ms=t_ms, ipc_cmd_id=snap.ipc_cmd_id)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n(stop)")
    finally:
        if trace is not None:
            trace.close()
        if log_path is not None and session_html and log_path.is_file():
            try:
                data = summarize(log_path)
                print(format_summary_line(data))
                html_out = finalize_session_report(log_path, summary=data)
                if html_out is not None:
                    print(f"replay -> {html_out.resolve()}")
                    if open_html:
                        import os

                        if session_ready_for_browser(data):
                            os.startfile(str(html_out.resolve()))  # type: ignore[attr-defined]
                        else:
                            print(
                                "replay guardado (no se abre navegador: sesion corta; "
                                "conduce 1-2 min antes de Ctrl+C)"
                            )
                else:
                    print(
                        f"replay omitido (<{MIN_HTML_TICKS} ticks o <{MIN_HTML_DURATION_S}s) "
                        f"— JSONL: {log_path.resolve()}"
                    )
            except (OSError, ValueError) as exc:
                print(f"AVISO: no se pudo generar replay HTML: {exc}", file=sys.stderr)
        if profile_path is not None and learner.brake_fill_n > 0:
            try:
                learner.save_json(profile_path)
                print(f"perfil -> {profile_path.resolve()} (fill={learner.brake_fill_s:.2f}s)")
            except OSError as exc:
                print(f"AVISO: no se pudo guardar perfil: {exc}", file=sys.stderr)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="tsw6v2", description="TSW6 proyecto V2")
    sub = parser.add_subparsers(dest="command")

    console_p = sub.add_parser("console", help="Bucle agente sin GUI")
    console_p.add_argument("--hz", type=float, default=DEFAULT_LOOP_HZ)
    console_p.add_argument("--duration", type=float, default=None)
    console_p.add_argument(
        "--mode",
        choices=sorted(P1_MODES - {"console"}),
        default=None,
        help="P1: limit (cartel), station, signal, p1 (todo cuando exista)",
    )
    console_p.add_argument(
        "--limit-brake",
        action="store_true",
        help="Atajo: igual que --mode limit",
    )
    console_p.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="JSON learner (decel_by_notch)",
    )
    console_p.add_argument(
        "--log",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="JSONL por tick (default logs/v2/<ts>_<route>_<mode>.jsonl)",
    )
    console_p.add_argument(
        "--investigate",
        action="store_true",
        help="Línea compacta P1 por tick",
    )
    console_p.add_argument(
        "--route",
        default="",
        help="Etiqueta de ruta en metadatos (ej. cross-city)",
    )
    console_p.add_argument(
        "--no-session-html",
        action="store_true",
        help="No generar replay HTML al cerrar (solo JSONL)",
    )
    console_p.add_argument(
        "--open-html",
        action="store_true",
        help="Abrir replay HTML en el navegador al cerrar sesión",
    )

    sub.add_parser("test-ipc", help="Prueba B1 vía IPC (interactiva)")
    sub.add_parser("gui", help="Visor tkinter (snapshot agente, sin mandos)")

    args = parser.parse_args(argv)
    command: str | None = getattr(args, "command", None)
    if command == "console":
        log_arg = getattr(args, "log", None)
        mode_arg = getattr(args, "mode", None)
        route = str(getattr(args, "route", "") or "")
        p1_mode = mode_arg or ("limit" if getattr(args, "limit_brake", False) else "console")
        log_path: Optional[Path] = None
        if log_arg is not None:
            log_path = (
                default_log_path(mode=p1_mode, route=route or "session")
                if log_arg == ""
                else Path(log_arg)
            )
        return run_console(
            hz=float(getattr(args, "hz", DEFAULT_LOOP_HZ)),
            duration_s=getattr(args, "duration", None),
            mode=p1_mode,
            limit_brake=bool(getattr(args, "limit_brake", False)),
            profile_path=getattr(args, "profile", None),
            log_path=log_path,
            investigate=bool(getattr(args, "investigate", False)),
            route=route,
            session_html=not bool(getattr(args, "no_session_html", False)),
            open_html=bool(getattr(args, "open_html", False)),
        )
    if command == "test-ipc":
        return run_ipc_brake_test(interactive=True)
    if command == "gui":
        return run_gui()
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
