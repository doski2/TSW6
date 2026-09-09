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
from tsw6v2.p1_mode import (
    GUI_P1_MODES,
    P1_MODES,
    apply_p1_mode,
    gui_mode_to_loop_mode,
    resolve_p1_mode,
    session_trace_mode,
)
from tsw6v2.session_log import (
    SessionRecorder,
    make_session_recorder,
    save_learner_if_dirty,
    session_profile_note,
)
from tsw6v2.trace import format_investigate, resolve_session_log_path


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

    learner = LearnerProfile.from_json(profile_path) if profile_path else None
    loop = AgentLoop(
        learner=learner,
        auto_profile=profile_path is None,
    )
    loop.post_ipc_sleep_s = 0.0
    auto_profile_announced = profile_path is not None
    for note in apply_p1_mode(loop, p1_mode):
        print(f"AVISO: {note}", file=sys.stderr)

    interval = 1.0 / max(1.0, hz)
    t0 = time.monotonic()
    use_investigate = investigate or p1_mode != "console"

    recorder: Optional[SessionRecorder] = None
    if log_path is not None:
        print(f"log -> {log_path.resolve()}")

    print(f"TSW6 V2 agent - modo={p1_mode} - Ctrl+C para salir")
    try:
        while True:
            if duration_s is not None and (time.monotonic() - t0) >= duration_s:
                break
            snap = loop.step()
            profile_note = session_profile_note(loop, profile_path)
            if not auto_profile_announced and profile_note is not None:
                print(f"perfil <- {Path(profile_note).resolve()}")
                auto_profile_announced = True
            if log_path is not None:
                if recorder is None:
                    recorder = make_session_recorder(
                        log_path,
                        loop,
                        trace_mode=session_trace_mode(p1_mode),
                        route=route,
                        profile_path=profile_path,
                    )
                recorder.record(snap)
            if use_investigate:
                print(format_investigate(snap))
            else:
                mph = f"{snap.speed_mph:.1f}" if snap.speed_mph is not None else "?"
                print(
                    f"tick={snap.tick} seq={snap.seq} mph={mph} "
                    f"lever={snap.lever_notch} target={snap.target_notch} "
                    f"ipc={snap.ipc_sent}"
                )
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n(stop)")
    finally:
        loop.shutdown()
        if recorder is not None:
            result = recorder.finish(
                open_html=open_html,
                generate_html=session_html,
            )
            if result.message:
                print(result.message)
        profile_msg = save_learner_if_dirty(loop, profile_path)
        if profile_msg is not None:
            stream = sys.stderr if profile_msg.startswith("AVISO:") else sys.stdout
            print(profile_msg, file=stream)
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
    gui_p = sub.add_parser("gui", help="Visor tkinter + config P1 (Fase A)")
    gui_p.add_argument(
        "--mode",
        default="p1",
        help="off=probe; p1=cartel+andén (alias limit/station → p1). Valores: %(choices)s",
        choices=list(GUI_P1_MODES),
    )
    gui_p.add_argument("--profile", type=Path, default=None, help="JSON learner")
    gui_p.add_argument(
        "--log",
        nargs="?",
        const="",
        default="",
        metavar="PATH",
        help="JSONL al cerrar (por defecto logs/v2/…; PATH opcional)",
    )
    gui_p.add_argument("--no-log", action="store_true", help="No guardar JSONL/HTML al cerrar")
    gui_p.add_argument(
        "--route",
        default="cross-city",
        help="Etiqueta ruta en nombre de log y replay",
    )
    gui_p.add_argument(
        "--open-html",
        action="store_true",
        help="Abrir replay HTML al cerrar si la sesión es larga",
    )
    gui_p.add_argument(
        "--no-open-html",
        action="store_false",
        dest="open_html",
        help="No abrir navegador al cerrar",
    )
    gui_p.set_defaults(open_html=True)

    args = parser.parse_args(argv)
    command: str | None = getattr(args, "command", None)
    if command == "console":
        log_arg = getattr(args, "log", None)
        mode_arg = getattr(args, "mode", None)
        route = str(getattr(args, "route", "") or "")
        p1_mode = mode_arg or ("limit" if getattr(args, "limit_brake", False) else "console")
        console_log = resolve_session_log_path(
            log_arg,
            trace_mode=session_trace_mode(p1_mode),
            route=route,
            default_route="session",
        )
        return run_console(
            hz=float(getattr(args, "hz", DEFAULT_LOOP_HZ)),
            duration_s=getattr(args, "duration", None),
            mode=p1_mode,
            limit_brake=bool(getattr(args, "limit_brake", False)),
            profile_path=getattr(args, "profile", None),
            log_path=console_log,
            investigate=bool(getattr(args, "investigate", False)),
            route=route,
            session_html=not bool(getattr(args, "no_session_html", False)),
            open_html=bool(getattr(args, "open_html", False)),
        )
    if command == "test-ipc":
        return run_ipc_brake_test(interactive=True)
    if command == "gui":
        profile = getattr(args, "profile", None)
        log_arg = getattr(args, "log", None)
        gui_mode = str(getattr(args, "mode", "p1"))
        gui_trace_mode = session_trace_mode(
            gui_mode_to_loop_mode(gui_mode) if gui_mode != "off" else "console"
        )
        gui_log: Optional[Path] = None
        if not getattr(args, "no_log", False):
            gui_log = resolve_session_log_path(
                log_arg,
                trace_mode=gui_trace_mode,
                route=str(getattr(args, "route", "") or "gui"),
                default_route="gui",
            )
        return run_gui(
            mode=str(getattr(args, "mode", "p1")),
            profile_path=profile,
            log_path=gui_log,
            route=str(getattr(args, "route", "cross-city") or "cross-city"),
            open_html=bool(getattr(args, "open_html", True)),
            no_log=bool(getattr(args, "no_log", False)),
        )
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
