#!/usr/bin/env python3
"""
TSW6 Autopilot - Controlador automático de velocidad
======================================================
Lee telemetría del juego y controla automáticamente tracción y freno
para mantener velocidad dentro del límite y frenar antes de reducciones.

Fuentes de telemetría (en orden de preferencia):
  1. RailBridge Companion API (puerto 51160 - activa botón CMP en RailBridge)
  2. Modo manual (el usuario introduce velocidad por teclado)

Control: PowerBrakeHandle vía RPC (RailBridge), fallback a teclas A/D.

Arquitectura (3 capas separadas):
  TrainState       — instantánea inmutable de telemetría (fuente de verdad)
  SpeedDecider     — lógica de decisión pura (P1 + P2 + P3 + FSM)
  HandleController — ejecución de comandos (RPC / teclado)
  SafetyWatchdog   — override de emergencia

Requisitos: pip install requests colorama
"""

import ctypes
import ctypes.wintypes
import logging
import time
import sys
import os
import threading
import argparse
from pathlib import Path
from typing import Optional

try:
    from colorama import init, Fore, Style  # type: ignore[import-untyped]
    init(autoreset=False)
except ImportError:
    print("Faltan dependencias. Ejecuta: pip install requests colorama")
    sys.exit(1)

from tsw_keys import user32                                # noqa: E402
from tsw_connection import TswConnection                   # noqa: E402
from train_state import build_train_state                  # noqa: E402
from speed_decider import SpeedDecider                     # noqa: E402
from handle_controller import HandleController, SafetyWatchdog  # noqa: E402
from dashboard import render_dashboard, KeyListener        # noqa: E402
from profiler import Profiler, Sample                      # noqa: E402
from tsw_ocr import TswOcr                                 # noqa: E402

# ── Configuración ─────────────────────────────────────────────────────────────

TSW_HOST = "127.0.0.1"
TSW_PORT = 31270

KEY_PATHS = [
    r"C:\Users\doski\Documents\My Games\TrainSimWorld6\Saved\Config\CommAPIKey.txt",
    os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "My Games",
                 "TrainSimWorld6", "Saved", "Config", "CommAPIKey.txt"),
    r"C:\Program Files (x86)\Steam\steamapps\common\Train Sim World 6"
    r"\WindowsNoEditor\TS2Prototype\Saved\Config\CommAPIKey.txt",
]

# ── Windows API ───────────────────────────────────────────────────────────────

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int,
                                      ctypes.POINTER(ctypes.c_int))


def find_tsw_window() -> Optional[int]:
    """Devuelve el handle (hwnd) de la ventana principal de TSW6."""
    found: list[int] = []

    @EnumWindowsProc
    def _cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if "Train Sim World" in title or "TrainSimWorld" in title:
                    found.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)
    return found[0] if found else None


# ── Lectura de API key ─────────────────────────────────────────────────────────

def load_api_key() -> Optional[str]:
    for path in KEY_PATHS:
        if os.path.exists(path):
            try:
                key = open(path, encoding="utf-8").read().strip()  # noqa: SIM115
                if key:
                    return key
            except OSError:
                pass
    return None


# ── Modo manual de telemetría ─────────────────────────────────────────────────

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
            "speed_mph":       speed,
            "limit_mph":       limit,
            "next_limit_mph":  next_lim,
            "distance_next_m": dist_next,
        }
    except (ValueError, KeyboardInterrupt):
        return {}


# ── Bucle principal ───────────────────────────────────────────────────────────

def main():
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
    parser.add_argument("--profile", action="store_true",
                        help="Registrar datos de calibración mientras conduce")
    args = parser.parse_args()

    print(Fore.CYAN + Style.BRIGHT + "\n  TSW6 Autopilot  –  iniciando...\n" + Style.RESET_ALL)

    # ── Logging a fichero ────────────────────────────────────────────────
    _log_dir  = Path(__file__).parent / "logs"
    _log_dir.mkdir(exist_ok=True)
    _log_path = _log_dir / f"autopilot_{time.strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s.%(msecs)03d [%(name)-14s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(_log_path, encoding="utf-8")],
    )
    _log = logging.getLogger("tsw.autopilot")
    _log.info("Autopilot iniciado  –  log: %s", _log_path)
    print(Fore.CYAN + f"  Log: {_log_path}" + Style.RESET_ALL)

    # ── Conexión y dispositivos ──────────────────────────────────────────
    conn = TswConnection()
    if args.manual:
        conn.mode = "manual"

    hwnd = find_tsw_window()
    ocr  = TswOcr(hwnd or 0)

    # ── Módulos de control (nueva arquitectura) ──────────────────────────
    decider    = SpeedDecider(target_mph=args.target)
    controller = HandleController()
    watchdog   = SafetyWatchdog()

    if args.stop is not None:
        decider.target_stop_min_m = args.stop * 1609.344
        _log.info("Parada manual: %.2f millas (%.0f m)",
                  args.stop, decider.target_stop_min_m)

    # ── Profiler de calibración (opcional) ──────────────────────────────
    _profiler: Optional[Profiler] = None
    _prof_last_notch: Optional[int] = None
    _prof_notch_since: float = 0.0
    _PROF_STABLE_S = 1.5
    if args.profile:
        _profiler = Profiler(vehicle_name="autopilot", output_dir=str(_log_dir))
        print(Fore.CYAN + "  Profiler activo – registrando calibración automática" + Style.RESET_ALL)

    kl = KeyListener()
    kl.start()

    # ── Background probe de reconexión ───────────────────────────────────
    _probe_lock = threading.Lock()
    PROBE_INTERVAL = 5.0

    def _bg_probe():
        conn.probe()
        while True:
            time.sleep(PROBE_INTERVAL)
            with _probe_lock:
                if conn.mode == "searching":
                    conn.probe()

    threading.Thread(target=_bg_probe, daemon=True).start()

    # ── Estado de sincronización del handle ──────────────────────────────
    _handle_synced = False
    _last_state_handle: int = 4  # para reset_neutral al salir

    telem: dict = {}
    loop_times: list[float] = []

    try:
        while True:
            t0 = time.perf_counter()

            # Obtener telemetría
            if conn.mode in ("manual", "searching"):
                if conn.mode == "manual":
                    telem = read_manual_telemetry() or telem
            else:
                new = conn.get_telemetry()
                if new:
                    telem = new

            # Reconectar ventana TSW si desapareció
            if not hwnd:
                hwnd = find_tsw_window()
                if hwnd:
                    ocr._hwnd = hwnd

            # Comandos del usuario (teclado consola)
            while True:
                cmd = kl.pop()
                if cmd is None:
                    break
                if cmd == 'Q':
                    raise KeyboardInterrupt
                elif cmd == 'P':
                    decider.paused = not decider.paused
                elif cmd == 'R':
                    if not args.no_control:
                        controller.reset_neutral(hwnd, _last_state_handle)
                elif cmd == 'N':
                    if not args.no_control:
                        print(f"\n  {Fore.YELLOW}Sincronizando handle (~5s)...{Style.RESET_ALL}")
                        _log.info("Tecla N: force_neutral manual")
                        controller.force_neutral(hwnd, conn)
                        _handle_synced = True
                elif cmd in ('+', '=') and decider.target_mph < 200:
                    decider.target_mph += 5
                elif cmd in ('-', '_') and decider.target_mph > 0:
                    decider.target_mph = max(0, decider.target_mph - 5)
                elif cmd == 'S':
                    print(f"\n{Fore.CYAN}Distancia a próxima parada en millas"
                          f" (0=sin paradas, Enter=auto): {Style.RESET_ALL}",
                          end="", flush=True)
                    try:
                        raw = input().strip()
                        if raw == "":
                            decider.target_stop_min_m  = None
                            decider._locked_stop_name  = None
                            _log.info("Parada manual desactivada – modo automático")
                        else:
                            miles = float(raw)
                            decider.target_stop_min_m = miles * 1609.344
                            decider._locked_stop_name = None
                            _log.info("Parada manual: %.2f millas (%.0f m)",
                                      miles, decider.target_stop_min_m)
                    except ValueError:
                        pass

            # ── Telemetría: sincronización del handle ─────────────────────
            speed       = telem.get("speed_mph")
            limit       = telem.get("limit_mph")
            api_accel   = telem.get("accel_mps2")
            handle_notch = telem.get("handle_notch")

            if handle_notch is not None:
                _last_state_handle = int(handle_notch)
                _handle_synced = True
            elif not _handle_synced:
                if telem.get("ack_required"):
                    # El ATP ya tiene control: no tiene sentido sincronizar
                    # físicamente. El companion posicionará el handle; nosotros
                    # lo leeremos en cuanto llegue handle_notch en telemetría.
                    _log.warning(
                        "handle_notch no disponible con ACK activo — "
                        "omitiendo force_neutral (ATP tiene control).")
                    _last_state_handle = 4  # neutro como fallback seguro
                elif not args.no_control:
                    _log.warning(
                        "handle_notch no disponible — sincronizando handle físicamente (~5s).")
                    controller.force_neutral(hwnd, conn)
                else:
                    _log.warning(
                        "handle_notch no disponible — asumiendo neutro (no_control activo).")
                _handle_synced = True

            # ── Actualizar física (acelerómetro + learner) ────────────────
            if speed is not None:
                decider.update_physics(
                    speed_mph   = speed,
                    api_accel   = api_accel,
                    gradient_pct= telem.get("gradient_pct") or 0.0,
                )
                decider.feed_learner(
                    speed_mph   = speed,
                    handle_notch= _last_state_handle,
                    gradient_pct= telem.get("gradient_pct") or 0.0,
                    accel_ms2   = api_accel,
                )

            # ── Rain ─────────────────────────────────────────────────────
            _rain = telem.get("rain_intensity", 0.0) or 0.0
            decider.set_rain_intensity(_rain)

            # ── OCR ──────────────────────────────────────────────────────
            _ocr_dist = ocr.get_distance()
            _ocr_task = ocr.get_task()

            # ── Construir TrainState ──────────────────────────────────────
            # ── Ciclo de control ─────────────────────────────────────────
            if speed is not None and limit is not None and conn.mode != "searching":
                state = build_train_state(
                    telem,
                    target_mph      = decider.target_mph,
                    paused          = decider.paused,
                    acceleration_ms2= decider.acceleration_ms2,
                    station_state   = decider.station_state,
                    station_name    = decider.station_name,
                    ocr_stop_dist_m = _ocr_dist,
                    ocr_task        = _ocr_task,
                )

                # ── Las 4 líneas del nuevo diseño ─────────────────────────
                action   = decider.decide(state)
                override = watchdog.check(state)
                final    = override or action

                if not args.no_control:
                    controller.execute(final, state, conn, hwnd)

                # ── Log de ciclo ─────────────────────────────────────────
                _dmi_d     = telem.get("doors_dmi")
                _dmi_d_str = "O" if _dmi_d is True else ("C" if _dmi_d is False else "?")
                _log.debug(
                    "spd=%5.1f  lim=%4.1f  elim=%5.1f  notch=%-2s  action=%-11s  "
                    "final=%-11s  fsm=%-10s  stop=%-30s  next=%s@%sm  ack=%s  sup=%-4s  "
                    "doors=%s  dmi_d=%s  grad=%s  ocr=%s  task=%s  rain=%.2f",
                    speed, limit,
                    decider.effective_limit,
                    telem.get("handle_notch", "?"),
                    action,
                    final,
                    decider.station_state or "-",
                    decider.station_name  or "-",
                    f"{telem.get('next_limit_mph', '?')}",
                    f"{telem.get('distance_next_m', '?')}",
                    "Y" if telem.get("ack_required") else "N",
                    telem.get("supervision", "?"),
                    "Y" if telem.get("doors_open") else "N",
                    _dmi_d_str,
                    f"{telem.get('gradient_pct') or 0.0:+.1f}%",
                    f"{_ocr_dist:.1f}m" if _ocr_dist is not None else "-",
                    _ocr_task or "-",
                    _rain,
                )
            else:
                decider.last_action = "HOLD"

            # ── Profiler: registrar muestra si notch lleva ≥1.5s estable ─
            if _profiler is not None:
                cur_notch = telem.get("handle_notch")
                now = time.perf_counter()
                if cur_notch != _prof_last_notch:
                    _prof_last_notch   = cur_notch
                    _prof_notch_since  = now
                elif (cur_notch is not None and speed is not None
                      and now - _prof_notch_since >= _PROF_STABLE_S):
                    stations   = telem.get("stations") or []
                    nxt        = stations[0] if stations else None
                    sample     = Sample(
                        t=time.time(),
                        speed=speed,
                        notch=cur_notch,
                        grad=telem.get("gradient_pct") or 0.0,
                        accel=telem.get("accel_mps2"),
                        next_stop=nxt["name"]              if nxt else None,
                        next_stop_dist=nxt["distance_m"]   if nxt else None,
                        next_stop_plat_m=nxt.get("platform_length_m") if nxt else None,
                        limit_mph=limit,
                        service=telem.get("service_name"),
                    )
                    _profiler.feed(sample, corrupt=telem.get("ack_required", False))

            # FPS
            elapsed    = time.perf_counter() - t0
            loop_times.append(elapsed)
            if len(loop_times) > 20:
                loop_times.pop(0)
            fps = 1.0 / (sum(loop_times) / len(loop_times)) if loop_times else 0.0

            # Render
            render_dashboard(decider, telem, conn, hwnd, fps)

            # Esperar resto del ciclo (~5 Hz en modo API, 0.5 Hz manual)
            target_dt = 0.2 if conn.mode != "manual" else 1.0
            time.sleep(max(0.0, target_dt - elapsed))

    except KeyboardInterrupt:
        pass

    # ── Limpieza ─────────────────────────────────────────────────────────
    ocr.stop()

    if _profiler is not None:
        print(f"\n  {Fore.CYAN}Guardando datos de calibración...{Style.RESET_ALL}")
        _profiler.summarize()

    if not args.no_control and hwnd:
        print(f"\n  {Fore.YELLOW}Llevando maneta a posición neutra...{Style.RESET_ALL}")
        controller.reset_neutral(hwnd, _last_state_handle)

    print(f"\n  {Fore.GREEN}Autopilot detenido. ¡Buen viaje!{Style.RESET_ALL}\n")


if __name__ == "__main__":
    main()
