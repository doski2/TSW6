#!/usr/bin/env python3
"""
TSW6 Autopilot - Controlador automático de velocidad
======================================================
Lee telemetría del juego y controla automáticamente tracción y freno
para mantener velocidad dentro del límite y frenar antes de reducciones.

Fuentes de telemetría (en orden de preferencia):
  1. RailBridge Companion API (puerto 51160 - activa botón CMP en RailBridge)
  2. Modo manual (el usuario introduce velocidad por teclado)

Control: PostMessage a ventana TSW con teclas A (acelerar) / D (frenar)
         Sin necesidad de tener TSW en primer plano.

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

from tsw_keys import user32                          # noqa: E402
from tsw_connection import TswConnection             # noqa: E402
from speed_governor import SpeedGovernor             # noqa: E402
from dashboard import render_dashboard, KeyListener  # noqa: E402
from profiler import Profiler, Sample                # noqa: E402
from tsw_ocr import TswOcr                           # noqa: E402

# ── Configuración ─────────────────────────────────────────────────────────────

TSW_HOST  = "127.0.0.1"
TSW_PORT  = 31270

# Rutas de la API key de TSW (probadas en orden)
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
    """Carga la CommAPIKey de TSW desde los archivos conocidos."""
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
    """Pide velocidad/límite al usuario (modo sin API disponible)."""
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
                        help="Distancia en millas a la próxima parada (omite estaciones intermedias)")
    parser.add_argument("--profile", action="store_true",
                        help="Registrar datos de calibración mientras el autopilot conduce")
    args = parser.parse_args()

    print(Fore.CYAN + Style.BRIGHT + "\n  TSW6 Autopilot  –  iniciando...\n" + Style.RESET_ALL)

    # ── Logging a fichero ────────────────────────────────────────────────────
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

    # Conexión: arranque inmediato, el background hace el probe
    conn = TswConnection()
    if args.manual:
        conn.mode = "manual"

    # Ventana TSW
    hwnd = find_tsw_window()

    # OCR del panel de tareas (distancia precisa al marcador de parada)
    # Si hwnd es None, TswOcr arranca igual pero _read_once devolverá None
    # hasta que find_tsw_window() encuentre la ventana en el bucle principal.
    ocr = TswOcr(hwnd or 0)

    # Gobernador de velocidad
    gov = SpeedGovernor(target_mph=args.target)
    if args.stop is not None:
        gov.target_stop_min_m = args.stop * 1609.344
        _log.info("Parada manual configurada: %.2f millas (%.0f m)",
                  args.stop, gov.target_stop_min_m)

    # Profiler de calibración (opcional)
    _profiler: Optional[Profiler] = None
    _prof_last_notch: Optional[int] = None
    _prof_notch_since: float = 0.0
    _PROF_STABLE_S = 1.5   # notch debe ser estable ≥1.5 s para registrar
    if args.profile:
        _profiler = Profiler(vehicle_name="autopilot",
                             output_dir=str(_log_dir))
        print(Fore.CYAN + "  Profiler activo — registrando calibración automática" + Style.RESET_ALL)

    # Listener de teclado (consola)
    kl = KeyListener()
    kl.start()

    # ── Reintento de conexión en segundo plano ───────────────────────────────
    _probe_lock = threading.Lock()
    PROBE_INTERVAL = 5.0

    def _bg_probe():
        """Intenta reconectar en background si estamos en modo 'searching'."""
        conn.probe()
        while True:
            time.sleep(PROBE_INTERVAL)
            with _probe_lock:
                if conn.mode == "searching":
                    conn.probe()

    bg = threading.Thread(target=_bg_probe, daemon=True)
    bg.start()
    # ── Sincronización inicial del handle ─────────────────────────────────────
    # Si la API no expone handle_notch (Class 323), la posición real es desconocida.
    # La primera telem puede tardar, así que esperamos 1 ciclo antes de decidir.
    _handle_synced = False
    # ── Bucle de control ──────────────────────────────────────────────────────
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
                    ocr._hwnd = hwnd   # actualizar hwnd en el hilo OCR

            # Comandos del usuario (teclado consola)
            while True:
                cmd = kl.pop()
                if cmd is None:
                    break
                if cmd == 'Q':
                    raise KeyboardInterrupt
                elif cmd == 'P':
                    gov.paused = not gov.paused
                elif cmd == 'R':
                    if not args.no_control:
                        gov.reset_neutral(hwnd)
                elif cmd == 'N':
                    if not args.no_control:
                        print(f"\n  {Fore.YELLOW}Sincronizando handle desde posición desconocida (~5 s)...{Style.RESET_ALL}")
                        _log.info("Tecla N: force_neutral manual")
                        gov.force_neutral(hwnd)
                        _handle_synced = True
                elif cmd in ('+', '=') and gov.target_mph < 200:
                    gov.target_mph += 5
                elif cmd in ('-', '_') and gov.target_mph > 0:
                    gov.target_mph = max(0, gov.target_mph - 5)
                elif cmd == 'S':
                    # Introducir distancia a próxima parada en millas
                    # Se muestra brevemente en consola; requiere pausa del render
                    print(f"\n{Fore.CYAN}Distancia a próxima parada en millas"
                          f" (0=sin paradas, Enter=auto): {Style.RESET_ALL}",
                          end="", flush=True)
                    try:
                        raw = input().strip()
                        if raw == "":
                            gov.target_stop_min_m = None
                            gov._locked_stop_name = None
                            _log.info("Parada manual desactivada – modo automático")
                        else:
                            miles = float(raw)
                            gov.target_stop_min_m = miles * 1609.344
                            gov._locked_stop_name = None   # forzar búsqueda de nueva parada
                            _log.info("Parada manual: %.2f millas (%.0f m)",
                                      miles, gov.target_stop_min_m)
                    except ValueError:
                        pass

            # Decisión de control
            speed = telem.get("speed_mph")
            limit = telem.get("limit_mph")
            if speed is not None:
                gov.record_speed(speed)
            # Aceleración nativa de la API (más precisa que dv/dt)
            api_accel = telem.get("accel_mps2")
            if api_accel is not None:
                gov._api_accel = api_accel
            # Sincronizar contadores internos con la muesca real del juego.
            # PowerBrakeHandle: 0=freno máx, 4=neutro, 8=tracción máx
            handle_notch = telem.get("handle_notch")
            if handle_notch is not None:
                if handle_notch <= 4:
                    gov.throttle.notch = 0
                    gov.brake.notch    = 4 - handle_notch
                else:
                    gov.throttle.notch = handle_notch - 4
                    gov.brake.notch    = 0
                _handle_synced = True
            elif not _handle_synced:
                # handle_notch aún no disponible (dashboard no ha llegado):
                # forzar sincronización física para garantizar que el juego
                # y el tracking interno arrancan desde neutro.
                if not args.no_control:
                    _log.warning(
                        "handle_notch no disponible — sincronizando handle "
                        "físicamente (~5 s).")
                    gov.force_neutral(hwnd)
                else:
                    _log.warning(
                        "handle_notch no disponible — asumiendo neutro "
                        "(no_control activo).")
                _handle_synced = True

            # Alimentar el aprendiz online con la telemetría del ciclo
            if speed is not None:
                gov.feed_learner(
                    speed,
                    telem.get("gradient_pct") or 0.0,
                    telem.get("accel_mps2"),
                )

            # OCR: capturar una sola vez para que decide() y el log usen
            # exactamente los mismos valores (el hilo OCR puede actualizar
            # entre dos llamadas separadas a get_distance/get_task).
            _ocr_dist = ocr.get_distance()
            _ocr_task = ocr.get_task()
            # En modo "searching" no hay telemetría fresca: evitar enviar
            # órdenes de control basadas en datos obsoletos del ciclo anterior.
            if speed is not None and limit is not None and conn.mode != "searching":
                _rain = telem.get("rain_intensity", 0.0) or 0.0
                gov.set_rain_intensity(_rain)
                action = gov.decide(
                    speed_mph=speed,
                    limit_mph=limit,
                    next_limit_mph=telem.get("next_limit_mph"),
                    distance_next_m=telem.get("distance_next_m"),
                    brake_marker_m=telem.get("brake_marker_m"),
                    gradient_pct=telem.get("gradient_pct"),
                    stations=telem.get("stations"),
                    doors_open=telem.get("doors_open", False),
                    ack_required=telem.get("ack_required", False),
                    ocr_stop_dist_m=_ocr_dist,
                    ocr_task=_ocr_task,
                    doors_dmi=telem.get("doors_dmi"),
                    supervision=telem.get("supervision", "csm"),
                )
                if not args.no_control:
                    gov.apply_action(action, hwnd, conn)
                # ── Log de ciclo ─────────────────────────────────────────────
                _dmi_d = telem.get("doors_dmi")
                _dmi_d_str = "O" if _dmi_d is True else ("C" if _dmi_d is False else "?")
                _log.debug(
                    "spd=%5.1f  lim=%4.1f  elim=%5.1f  notch=%-2s  action=%-11s  "
                    "fsm=%-10s  stop=%-30s  next=%s@%sm  ack=%s  sup=%-4s  "
                    "doors=%s  dmi_d=%s  grad=%s  ocr=%s  task=%s  rain=%.2f",
                    speed, limit,
                    gov.effective_limit,
                    telem.get("handle_notch", "?"),
                    action,
                    gov.station_state or "-",
                    gov.station_name  or "-",
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
                gov.last_action = "HOLD"

            # ── Profiler: registrar muestra si notch lleva ≥1.5 s estable ───
            if _profiler is not None:
                cur_notch = telem.get("handle_notch")
                now = time.perf_counter()
                if cur_notch != _prof_last_notch:
                    _prof_last_notch = cur_notch
                    _prof_notch_since = now
                elif (cur_notch is not None and speed is not None
                      and now - _prof_notch_since >= _PROF_STABLE_S):
                    stations = telem.get("stations") or []
                    nxt = stations[0] if stations else None
                    sample = Sample(
                        t=time.time(),
                        speed=speed,
                        notch=cur_notch,
                        grad=telem.get("gradient_pct") or 0.0,
                        accel=telem.get("accel_mps2"),
                        next_stop=nxt["name"]        if nxt else None,
                        next_stop_dist=nxt["distance_m"]      if nxt else None,
                        next_stop_plat_m=nxt.get("platform_length_m") if nxt else None,
                        limit_mph=limit,
                        service=telem.get("service_name"),
                    )
                    _profiler.feed(sample, corrupt=telem.get("ack_required", False))

            # FPS
            elapsed = time.perf_counter() - t0
            loop_times.append(elapsed)
            if len(loop_times) > 20:
                loop_times.pop(0)
            fps = 1.0 / (sum(loop_times) / len(loop_times)) if loop_times else 0.0

            # Render
            render_dashboard(gov, telem, conn, hwnd, fps)

            # Esperar resto del ciclo (objetivo: ~5 Hz en modo API, 0.5 Hz manual)
            target_dt = 0.2 if conn.mode != "manual" else 1.0
            sleep_t = max(0.0, target_dt - elapsed)
            time.sleep(sleep_t)

    except KeyboardInterrupt:
        pass

    # Detener hilo OCR
    ocr.stop()

    # Guardar calibración si el profiler estaba activo
    if _profiler is not None:
        print(f"\n  {Fore.CYAN}Guardando datos de calibración...{Style.RESET_ALL}")
        _profiler.summarize()

    # Llevar a neutro al salir
    if not args.no_control and hwnd:
        print(f"\n  {Fore.YELLOW}Llevando maneta a posición neutra...{Style.RESET_ALL}")
        gov.reset_neutral(hwnd)

    print(f"\n  {Fore.GREEN}Autopilot detenido. ¡Buen viaje!{Style.RESET_ALL}\n")


if __name__ == "__main__":
    main()
