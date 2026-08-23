#!/usr/bin/env python3
"""
TSW6 Autopilot - Controlador automático de velocidad
======================================================
Por defecto abre la GUI (autopilot_gui.py). Usa --console para consola.

Requisitos: pip install requests colorama
"""

import argparse
import logging
import sys
import time
from tsw6.paths import LOGS_DIR

try:
    from colorama import init, Fore, Style  # type: ignore[import-untyped]
    init(autoreset=False)
except ImportError:
    print("Faltan dependencias. Ejecuta: pip install requests colorama")
    sys.exit(1)

from tsw6.autopilot.autopilot_core import AutopilotConfig, AutopilotEngine  # noqa: E402
from tsw6.ui.dashboard import KeyListener, render_dashboard  # noqa: E402


def read_manual_telemetry() -> dict:
    print(Fore.YELLOW + "\n[Modo Manual] Introduce los datos del tren:")
    try:
        speed = float(input("  Velocidad actual (mph): "))
        limit = float(input("  Límite de velocidad (mph): "))
        next_lim_s = input("  Próximo límite (mph, Enter=no hay): ").strip()
        next_lim = None
        dist_next = None
        if next_lim_s:
            next_lim = float(next_lim_s)
            dist_s = input("  Distancia al próximo límite (m): ").strip()
            dist_next = float(dist_s) if dist_s else None
        return {
            "speed_mph": speed,
            "limit_mph": limit,
            "next_limit_mph": next_lim,
            "distance_next_m": dist_next,
        }
    except (ValueError, KeyboardInterrupt):
        return {}


def run_console(args: argparse.Namespace) -> None:
    print(Fore.CYAN + Style.BRIGHT + "\n  TSW6 Autopilot  –  consola\n" + Style.RESET_ALL)

    LOGS_DIR.mkdir(exist_ok=True)
    log_path = LOGS_DIR / f"autopilot_{time.strftime('%Y%m%d_%H%M%S')}.log"
    print(Fore.CYAN + f"  Log: {log_path}" + Style.RESET_ALL)

    config = AutopilotConfig(
        target_mph=args.target,
        no_control=args.no_control,
        manual=args.manual,
        learn=args.learn,
        stop_miles=args.stop,
        loop_hz=5.0,
    )
    engine = AutopilotEngine(config, log_path=log_path)
    logging.getLogger("tsw.autopilot").info("Autopilot consola iniciado")

    if config.manual:
        engine.set_manual_prompt(read_manual_telemetry)

    kl = KeyListener()
    kl.start()

    try:
        while True:
            t0 = time.perf_counter()

            while True:
                cmd = kl.pop()
                if cmd is None:
                    break
                if cmd == "Q":
                    raise KeyboardInterrupt
                if cmd == "P":
                    engine.toggle_pause()
                elif cmd == "R" and not config.no_control:
                    engine.reset_neutral()
                elif cmd == "N" and not config.no_control:
                    print(f"\n  {Fore.YELLOW}Sincronizando handle (~5s)...{Style.RESET_ALL}")
                    engine.force_neutral()
                elif cmd in ("+", "="):
                    engine.adjust_target(5)
                elif cmd in ("-", "_"):
                    engine.adjust_target(-5)
                elif cmd == "S":
                    print(f"\n{Fore.CYAN}Distancia a próxima parada en millas"
                          f" (Enter=auto): {Style.RESET_ALL}", end="", flush=True)
                    try:
                        raw = input().strip()
                        if raw == "":
                            engine.clear_stop()
                        else:
                            engine.set_stop_miles(float(raw))
                    except ValueError:
                        pass

            snap = engine.tick()
            render_dashboard(
                engine.decider, engine.telem, engine.conn, engine.hwnd, snap.fps)

            elapsed = time.perf_counter() - t0
            engine.sleep_remainder(elapsed)

    except KeyboardInterrupt:
        pass

    engine.stop()
    if not config.no_control:
        engine.reset_neutral()
    print(f"\n  {Fore.GREEN}Autopilot detenido. ¡Buen viaje!{Style.RESET_ALL}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TSW6 Autopilot – Controlador automático de velocidad")
    parser.add_argument("--target", type=float, default=0,
                        help="Velocidad objetivo en mph (0=seguir límite de vía)")
    parser.add_argument("--no-control", action="store_true",
                        help="Solo mostrar telemetría, no enviar controles")
    parser.add_argument("--manual", action="store_true",
                        help="Forzar introducción manual de telemetría")
    parser.add_argument("--stop", type=float, default=None, metavar="MILLAS",
                        help="Distancia en millas a la próxima parada")
    parser.add_argument("--learn", action="store_true",
                        help="Re-aprender la calibración en vivo")
    parser.add_argument("--console", action="store_true",
                        help="Usar consola en lugar de la GUI")
    args = parser.parse_args()

    if args.console:
        run_console(args)
    else:
        from tsw6.autopilot.autopilot_gui import launch
        from tsw6.autopilot.autopilot_core import AutopilotConfig
        launch(AutopilotConfig(
            target_mph=args.target,
            no_control=args.no_control,
            manual=args.manual,
            learn=args.learn,
            stop_miles=args.stop,
            loop_hz=10.0,
        ))


if __name__ == "__main__":
    main()
