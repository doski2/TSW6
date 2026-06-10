#!/usr/bin/env python3
"""
Dashboard — Renderizado del panel de control en consola (sin parpadeo).

Exporta render_dashboard() y las barras de progreso auxiliares.
"""

import os
import sys
import time
import threading
from typing import Optional

from colorama import Fore, Style

from typing import Any

from governor_constants import NOTCH_LABELS
from tsw_connection import TswConnection

# ── Colores por acción ────────────────────────────────────────────────────────

ACTION_COLOR: dict[str, str] = {
    "ACCELERATE": Fore.GREEN,
    "HOLD":       Fore.CYAN,
    "COAST":      Fore.YELLOW,
    "BRAKE":      Fore.RED,
    "HARDBRAKE":  Fore.RED + Style.BRIGHT,
    "FULLSTOP":   Fore.MAGENTA + Style.BRIGHT,
    "PAUSED":     Fore.WHITE + Style.DIM,
}

# ── Barras de progreso ────────────────────────────────────────────────────────

def throttle_bar(notch: int, width: int = 8) -> str:
    """Barra de tracción (0-4)."""
    filled = int((notch / 4) * width)
    bar = "█" * filled + "░" * (width - filled)
    color = Fore.GREEN if notch > 0 else Style.DIM
    return color + "[" + bar + "]" + Style.RESET_ALL


def brake_bar(notch: int, width: int = 8) -> str:
    """Barra de freno (0-4)."""
    filled = int((notch / 4) * width)
    bar = "█" * filled + "░" * (width - filled)
    color = Fore.RED if notch > 0 else Style.DIM
    return color + "[" + bar + "]" + Style.RESET_ALL


def speed_bar(speed: float, limit: float, width: int = 20) -> str:
    """Barra de velocidad con indicador de límite."""
    if limit <= 0:
        return ""
    ratio = min(speed / limit, 1.3)
    filled = min(int(ratio * width), width)
    over = ratio > 1.0
    bar = "█" * filled + "░" * (width - filled)
    color = Fore.RED if over else (Fore.YELLOW if ratio > 0.9 else Fore.GREEN)
    return color + "[" + bar + "]" + Style.RESET_ALL


def braking_bar(distance: float, needed: float, width: int = 16) -> str:
    """Barra de distancia al punto de frenado."""
    if needed <= 0:
        return Fore.GREEN + "[OK──────────────]" + Style.RESET_ALL
    ratio = distance / needed
    ratio = max(0.0, min(ratio, 2.0))
    filled = int((ratio / 2.0) * width)
    color = Fore.RED if ratio < 1.0 else (Fore.YELLOW if ratio < 1.5 else Fore.GREEN)
    bar = "█" * filled + "░" * (width - filled)
    return color + "[" + bar + "]" + Style.RESET_ALL


# ── Estado del render ─────────────────────────────────────────────────────────

_CURSOR_HOME = "\033[H"   # mover cursor a inicio sin limpiar (evita parpadeo)
_first_render = True       # primer render: limpiar pantalla una sola vez

# ── Dashboard principal ───────────────────────────────────────────────────────

def render_dashboard(gov: Any, telem: dict, conn: TswConnection,
                     hwnd: Optional[int], fps: float) -> None:
    """Renderiza el dashboard en consola sin parpadeo (sobreescribe en su sitio)."""
    global _first_render
    speed       = telem.get("speed_mph")
    limit       = telem.get("limit_mph")
    next_lim    = telem.get("next_limit_mph")
    dist_next   = telem.get("distance_next_m")

    speed_str   = f"{speed:5.1f} mph" if speed  is not None else "  ??? mph"
    limit_str   = f"{limit:.0f} mph"  if limit  is not None else "??? mph"
    target_str  = f"{gov.target_mph:.0f} mph" if gov.target_mph > 0 else "(límite)"

    action      = gov.last_action
    action_col  = ACTION_COLOR.get(action, Fore.WHITE)
    mode_str    = {"companion":  "RailBridge CMP ✓",
                   "tsw_api":    "TSW API directa ✓",
                   "manual":     "MANUAL",
                   "searching":  "Buscando conexión...",
                  }.get(conn.mode, conn.mode)
    mode_col    = Fore.GREEN  if conn.mode in ("companion", "tsw_api") else \
                  Fore.YELLOW if conn.mode == "manual" else Fore.RED
    hwnd_str    = f"hwnd={hwnd:#010x}" if hwnd else "ventana TSW no encontrada"

    # Distancia de frenado necesaria para próximo límite
    brake_marker = telem.get("brake_marker_m")
    if speed is not None and next_lim is not None and next_lim < (speed or 0):
        needed_brake = brake_marker if brake_marker is not None \
                       else gov.braking_distance(speed, next_lim)
        dist_str = f"{dist_next:5.0f} m" if dist_next is not None else "  ??? m"
        brake_bar_str = braking_bar(dist_next or 0, needed_brake)
        marker_info = f"[CMP {needed_brake:.0f}m]" if brake_marker is not None \
                      else f"(estimado {needed_brake:.0f} m)"
        needed_str = marker_info
    else:
        dist_str = "  ─── m"
        brake_bar_str = Fore.GREEN + "[OK──────────────]" + Style.RESET_ALL
        needed_str = ""

    sep = Fore.WHITE + Style.DIM + "─" * 58 + Style.RESET_ALL

    speed_col = Fore.RED if (speed or 0) > (limit or 999) + 2 else \
                (Fore.YELLOW if (speed or 0) > (limit or 999) - 1 else Fore.GREEN)
    notch_label = NOTCH_LABELS.get(gov.current_notch, f"Notch {gov.current_notch}")
    _th = gov.throttle_notch
    _br = gov.brake_notch
    _hn = telem.get("handle_notch")
    _hn_str = (f"{Fore.CYAN}API:{_hn:d}/8{Style.RESET_ALL}" if _hn is not None
               else f"{Style.DIM}API:?{Style.RESET_ALL}")

    # Acelómetro
    _accel = gov.acceleration_ms2
    _g     = gov.g_force
    _src   = "API" if gov._api_accel is not None else "dv/dt"
    if _accel is None:
        line_accel = f"  Acelerómetro : {Style.DIM}calculando...{Style.RESET_ALL}"
    else:
        if _accel > 0.08:
            _sym  = "▲"
            _acol = Fore.GREEN
        elif _accel < -0.08:
            _sym  = "▼"
            _acol = Fore.RED
        else:
            _sym  = "►"
            _acol = Fore.CYAN
        line_accel = (f"  Acelerómetro : {_acol}{_sym} {_accel:+.3f} m/s² "
                      f"({_g:+.4f} g)  {Style.DIM}[{_src}]{Style.RESET_ALL}")

    # Gradiente de vía
    _grad = telem.get("gradient_pct")
    if _grad is None:
        line_grad = f"  Gradiente    : {Style.DIM}desconocido{Style.RESET_ALL}"
    else:
        if _grad > 0.3:
            _gsym = "⬆"
            _gcol = Fore.YELLOW
        elif _grad < -0.3:
            _gsym = "⬇"
            _gcol = Fore.CYAN
        else:
            _gsym = "➡"
            _gcol = Fore.WHITE
        line_grad = f"  Gradiente    : {_gcol}{_gsym} {_grad:+.2f}%{Style.RESET_ALL}"

    # Paradas programadas
    _stations = telem.get("stations") or []
    _svc      = telem.get("service_name")
    _tid      = telem.get("train_id")
    if _svc and _svc not in ("None", "none", None):
        svc_str = f"{Fore.CYAN}{_tid or ''} {_svc}{Style.RESET_ALL}"
        line_service = f"  Servicio     : {svc_str}\033[K"
    else:
        line_service = f"  Servicio     : {Style.DIM}libre (sin horario){Style.RESET_ALL}\033[K"

    _dist_unit = telem.get("dist_unit", "m")
    _unit_tag  = (f" {Fore.MAGENTA}[yd→m]{Style.RESET_ALL}" if _dist_unit == "yd" else "")
    if _stations:
        stop_lines = []
        for st in _stations[:3]:
            d_mi = st["distance_m"] / 1609.344
            stop_lines.append(
                f"    {Fore.WHITE}● {st['name']:<22s}{Style.RESET_ALL}"
                f"  {Fore.YELLOW}{d_mi:5.2f} mi{Style.RESET_ALL}{_unit_tag}\033[K"
            )
        line_stops = "\n".join(stop_lines)
    else:
        line_stops = f"    {Style.DIM}(sin paradas programadas){Style.RESET_ALL}\033[K"

    # Indicador de modo de parada manual
    _min_m = getattr(gov, 'target_stop_min_m', None)
    _locked = getattr(gov, '_locked_stop_name', None)
    if _min_m is not None and _min_m <= 0:
        line_stop_mode = (f"  {Fore.MAGENTA}{Style.BRIGHT}⭑ MODO SIN PARADAS – "
                          f"pulse S para configurar{Style.RESET_ALL}\033[K")
    elif _locked is not None:
        line_stop_mode = (f"  {Fore.GREEN}{Style.BRIGHT}◎ PARADA MANUAL: {_locked}{Style.RESET_ALL}\033[K")
    elif _min_m is not None:
        _mi = _min_m / 1609.344
        line_stop_mode = (f"  {Fore.YELLOW}○ Buscando parada > {_mi:.1f} mi..."
                          f"{Style.RESET_ALL}\033[K")
    else:
        line_stop_mode = ""

    # Estado de parada en estación + puertas
    _sstate    = gov.station_state
    _sname     = gov.station_name
    _doors_open = telem.get("doors_open", False)
    _door_str  = (f"  {Fore.RED}{Style.BRIGHT}🚪 PUERTAS ABIERTAS{Style.RESET_ALL}"
                  if _doors_open else "")
    if _sstate == "APPROACHING":
        _st_dist  = (_stations[0]["distance_m"] if _stations else 0)
        _u_tag    = " yd→m" if _dist_unit == "yd" else " m"
        _creeping = getattr(gov, "_creep_to_station", False)
        if _creeping:
            line_station_state = (
                f"  {Fore.CYAN}{Style.BRIGHT}▷ AVANZANDO → {_sname or '?'}"
                f"  ({_st_dist:.0f}{_u_tag}){Style.RESET_ALL}\033[K"
            )
        else:
            line_station_state = (
                f"  {Fore.YELLOW}{Style.BRIGHT}⬤ FRENANDO → {_sname or '?'}"
                f"  ({_st_dist:.0f}{_u_tag}){Style.RESET_ALL}\033[K"
            )
    elif _sstate == "STOPPED":
        if _doors_open:
            line_station_state = (
                f"  {Fore.RED}{Style.BRIGHT}■ EN ANDÉN: {_sname or '?'}"
                f"  ⏸ esperando cierre de puertas{Style.RESET_ALL}\033[K"
            )
        else:
            line_station_state = (
                f"  {Fore.GREEN}{Style.BRIGHT}■ EN ANDÉN: {_sname or '?'}"
                f"  puertas cerradas — saliendo...{Style.RESET_ALL}\033[K"
            )
    elif _sstate == "DEPARTING":
        line_station_state = (
            f"  {Fore.CYAN}{Style.BRIGHT}▶ SALIENDO DE {_sname or '?'}"
            f"{Style.RESET_ALL}\033[K"
        )
    else:
        line_station_state = _door_str   # fuera de estación: solo muestra si hay puertas abiertas

    if conn.mode == "searching":
        line_conn1 = f"  {Style.DIM}  Último intento: {conn.last_probe_info}{Style.RESET_ALL}"
        line_conn2 = f"  {Fore.YELLOW}  → Abre TSW6 y/o activa el botón CMP en RailBridge{Style.RESET_ALL}"
    else:
        line_conn1 = f"  {Style.DIM}{hwnd_str}{Style.RESET_ALL}"
        line_conn2 = ""

    if next_lim is not None:
        line_next = (f"  Próx. límite: {Fore.YELLOW}{next_lim:.0f} mph{Style.RESET_ALL}"
                     f"  a  {dist_str}  {brake_bar_str} {needed_str}")
    else:
        line_next = f"  Próx. límite: {Style.DIM}desconocido{Style.RESET_ALL}"

    if gov.paused:
        line_state = f"  {Fore.YELLOW}{Style.BRIGHT}[ AUTOPILOT EN PAUSA – pulse P para reanudar ]{Style.RESET_ALL}"
    else:
        line_state = (f"  {Fore.GREEN}[ AUTOPILOT ACTIVO ]{Style.RESET_ALL}"
                      f"   P=pausar  Q=salir  +/-=target  R=neutro  S=parada")

    if _first_render:
        os.system("cls")
        _first_render = False
        prefix = ""
    else:
        prefix = _CURSOR_HOME

    dashboard = (
        prefix
        + Fore.CYAN + Style.BRIGHT
        + "╔══════════════════════════════════════════════════════╗\n"
        + "║         TSW6 AUTOPILOT  –  Controlador Automático   ║\n"
        + "╚══════════════════════════════════════════════════════╝" + Style.RESET_ALL + "\n"
        + f"  Fuente datos : {mode_col}{mode_str}{Style.RESET_ALL}\033[K\n"
        + line_conn1 + "\033[K\n"
        + line_conn2 + "\033[K\n"
        + sep + "\033[K\n"
        + f"  Velocidad   : {speed_col}{Style.BRIGHT}{speed_str}{Style.RESET_ALL}"
          f"   {speed_bar(speed or 0, limit or 1)}\033[K\n"
        + f"  Límite act. : {Fore.WHITE}{limit_str}{Style.RESET_ALL}"
          f"   Objetivo: {Fore.CYAN}{target_str}{Style.RESET_ALL}\033[K\n"
        + line_next + "\033[K\n"
        + sep + "\033[K\n"
        + f"  Tracción    : {throttle_bar(_th)} {_th}/4   "
          f"Freno: {brake_bar(_br)} {_br}/4   "
          f"{_hn_str}  {Style.DIM}{notch_label}{Style.RESET_ALL}\033[K\n"
        + line_accel + "\033[K\n"
        + line_grad  + "\033[K\n"
        + sep + "\033[K\n"
        + line_service + "\n"
        + line_stops  + "\n"
        + (line_stop_mode + "\n" if line_stop_mode else "")
        + (line_station_state + "\n" if line_station_state else "")
        + f"  Acción      : {action_col}{Style.BRIGHT}{action:12s}{Style.RESET_ALL}"
          f"   {fps:.1f} Hz\033[K\n"
        + sep + "\033[K\n"
        + line_state + "\033[K\n"
        + "\033[K\n"
    )
    sys.stdout.write(dashboard)
    sys.stdout.flush()


# ── Listener de teclado (reutilizable) ───────────────────────────────────────

class KeyListener(threading.Thread):
    """Lee teclas del usuario en segundo plano (sin bloquear el bucle principal)."""

    def __init__(self):
        super().__init__(daemon=True)
        self._queue: list[str] = []
        self._lock = threading.Lock()

    def run(self) -> None:
        import msvcrt
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    msvcrt.getwch()    # leer segundo byte de teclas especiales
                    continue
                key = ch.upper()
                with self._lock:
                    self._queue.append(key)
            else:
                time.sleep(0.05)

    def pop(self) -> Optional[str]:
        """Devuelve la siguiente tecla pulsada o None si no hay ninguna."""
        with self._lock:
            return self._queue.pop(0) if self._queue else None
