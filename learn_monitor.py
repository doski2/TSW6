#!/usr/bin/env python3
"""
learn_monitor.py — Monitor de aprendizaje guiado para calibración del tren.

A diferencia de profiler.py (que solo escucha pasivamente), este monitor te
GUÍA: muestra una matriz de objetivos (muesca × banda de velocidad), te dice
qué hacer en cada momento para completar las celdas que faltan, y alimenta el
OnlineLearner en vivo — de modo que logs/calibration.json se actualiza mientras
conduces manualmente.

Cuando todas las celdas están completas, el autopilot sabe exactamente cuánto
acelera y frena cada muesca en cada rango de velocidad.

Objetivo de cada celda: TARGET_SAMPLES muestras limpias
(muesca estable ≥ 2 s, cambio de velocidad apreciable, |gradiente| < 3 %).

Uso:
    python learn_monitor.py
    python learn_monitor.py --host 192.168.1.5
    python learn_monitor.py --target 5      (muestras por celda)
    python learn_monitor.py --reset         (borra calibration.json y empieza de cero)
"""

import argparse
import os
import sys
import threading
import time
from typing import Optional

from profiler import COMP_PORT, get_vehicle_name, notch_label
from tsw_connection import TswConnection
from online_learner import (
    OnlineLearner, path_for_vehicle, _SPEED_BANDS, _speed_band_index,
)

# ── Configuración ─────────────────────────────────────────────────────────────

TARGET_SAMPLES = 8   # muestras limpias por celda para marcarla como completada

# Muescas que el learner realmente observa (5 y 6 = Tracción-1/2 no se calibran:
# el learner promedia 7 y 8 para TARGET_ACCEL). Orden lógico para la matriz.
_NOTCH_ROWS = [0, 1, 2, 3, 4, 5, 6, 7, 8]


def _enable_utf8() -> None:
    """Fuerza UTF-8 en stdout para los caracteres de caja en consola Windows."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _bar(pct: float, width: int = 30) -> str:
    filled = int(round(pct * width))
    return "█" * filled + "·" * (width - filled)


class LearnMonitor:
    """Dashboard guiado sobre el conteo de muestras del OnlineLearner."""

    def __init__(self, learner: OnlineLearner, vehicle: str, target: int,
                 vehicle_known: bool = True):
        self.learner = learner
        self.vehicle = vehicle
        self.target = target
        self.vehicle_known = vehicle_known

        self._last_render = 0.0
        self._last_save = 0.0
        self._ack_active = False
        self._snaps = 0
        self._cur_accel: Optional[float] = None

        # Último estado visto (para la cabecera)
        self._cur_speed = 0.0
        self._cur_notch = 4
        self._cur_grad = 0.0
        self._cur_band = 0
        self._cur_limit: Optional[float] = None

    # ── Conteo de muestras por celda (lee el estado interno del learner) ──────

    def _count(self, band: int, notch: int) -> int:
        return self.learner._n_bands[band].get(notch, 0)

    def _is_complete(self, band: int, notch: int) -> bool:
        return self._count(band, notch) >= self.target

    def _total_progress(self) -> tuple[int, int]:
        done = sum(
            1 for b in range(len(_SPEED_BANDS)) for n in _NOTCH_ROWS
            if self._is_complete(b, n)
        )
        total = len(_SPEED_BANDS) * len(_NOTCH_ROWS)
        return done, total

    def render_waiting(self, speed: Optional[float]) -> None:
        """Pantalla de espera hasta conocer la muesca (llega solo al cambiar)."""
        now = time.time()
        if now - self._last_render < 0.5:
            return
        self._last_render = now
        _clear()
        print("═" * 64)
        print(f"  MONITOR DE APRENDIZAJE   ·   {self.vehicle}")
        print("═" * 64)
        spd = f"{speed:.1f} mph" if speed is not None else "?"
        print(f"  Esperando posición del acelerador…   (velocidad: {spd})")
        print()
        print("  El companion solo envía la muesca cuando CAMBIA.")
        print("  ► Mueve el acelerador/freno una muesca para que se detecte.")
        print(f"  Snapshots recibidos: {self._snaps}")
        print("═" * 64)

    # ── Procesar una muestra de telemetría ───────────────────────────────────

    def feed(self, speed: float, notch: int, grad: float,
             accel: Optional[float], limit: Optional[float],
             ack: bool) -> None:
        self._cur_speed = speed
        self._cur_notch = notch
        self._cur_grad = grad
        self._cur_band = _speed_band_index(speed)
        self._cur_limit = limit
        self._cur_accel = accel

        # Durante intervención del ATP los datos no son fiables: no aprender
        self._ack_active = ack
        if not ack:
            self.learner.feed(speed, notch, grad, accel)

        now = time.time()

        # Autoguardado periódico (cada 5 s) para no perder progreso aunque
        # ninguna muesca haya llegado aún a una constante confiable, ni siquiera
        # si se cierra la ventana de la consola sin Ctrl+C. Mientras el tren es
        # "Desconocido" se guarda en su perfil temporal; al detectar el nombre,
        # adopt_profile fusiona todo y se borra ese temporal.
        if now - self._last_save >= 5.0:
            self._last_save = now
            self.learner.save()

        # Refrescar pantalla como máximo 2 veces/s para evitar parpadeo
        if now - self._last_render >= 0.5:
            self._last_render = now
            self.render()

    # ── Captura oportunista (se adapta a ti, no al revés) ─────────────────────

    def _pending_in_band(self, band: int) -> list[int]:
        return [n for n in _NOTCH_ROWS if not self._is_complete(band, n)]

    def _hints(self) -> list[str]:
        """
        Devuelve líneas informativas/opcionales. Nunca exige una acción que
        contradiga el límite o la parada del escenario: solo informa de lo que
        falta y, si el margen al límite lo permite, ofrece una sugerencia.
        """
        band = self._cur_band
        lo, hi = _SPEED_BANDS[band]
        pending = self._pending_in_band(band)

        # Si esta muesca está capturando ahora mismo, dilo (feedback positivo)
        capturando = ""
        if self._cur_notch in _NOTCH_ROWS and not self._is_complete(band, self._cur_notch):
            need = self.target - self._count(band, self._cur_notch)
            capturando = (f"Capturando {notch_label(self._cur_notch)} "
                          f"@ {lo}-{hi} mph  → faltan {need}")

        if not pending:
            remaining = any(self._pending_in_band(b)
                            for b in range(len(_SPEED_BANDS)))
            if not remaining:
                return ["¡Todas las celdas completas! El tren está calibrado."]
            return [f"Banda {lo}-{hi} mph completa. "
                    "Se seguirá capturando cuando el escenario te lleve a "
                    "otra velocidad."]

        lines: list[str] = []
        if capturando:
            lines.append(capturando)

        nombres = ", ".join(notch_label(n) for n in pending)
        lines.append(f"Pendiente en {lo}-{hi} mph: {nombres}")

        # Sugerencia opcional según el margen al límite actual
        limit = self._cur_limit
        if limit is not None and limit > 0:
            margin = limit - self._cur_speed
            tracc = [n for n in pending if n >= 7]
            freno = [n for n in pending if n <= 3]
            neutro = 4 in pending
            if margin > 5 and tracc:
                lines.append(
                    f"Margen ~{margin:.0f} mph al límite ({limit:.0f}): "
                    f"si el escenario lo permite, acelerar captura "
                    f"{', '.join(notch_label(n) for n in tracc)}.")
            elif margin <= 3 and freno:
                lines.append(
                    f"Al frenar para el próximo límite/parada, mantén un freno "
                    f"constante unos segundos para capturar "
                    f"{', '.join(notch_label(n) for n in freno)}.")
            elif margin <= 3 and neutro:
                lines.append(
                    f"Cerca del límite ({limit:.0f} mph): dejar en "
                    f"{notch_label(4)} captura inercia.")

        lines.append("Solo cuando los límites y las paradas del escenario te lo permitan.")
        return lines

    # ── Render ────────────────────────────────────────────────────────────────

    def render(self) -> None:
        _clear()
        done, total = self._total_progress()
        pct = done / total if total else 0.0

        veh_str = self.vehicle
        if not self.vehicle_known:
            veh_str += "  (buscando nombre del tren…)"
        print("═" * 64)
        print(f"  MONITOR DE APRENDIZAJE (captura oportunista)   ·   {veh_str}")
        print(f"  Conduce el escenario normalmente — el monitor se adapta a ti.")
        print(f"  Objetivo por celda: {self.target} muestras   "
              f"·   perfil: {os.path.basename(self.learner.save_path)}")
        print("═" * 64)

        # Cabecera de columnas (bandas de velocidad)
        col_hdr = "  " + f"{'Muesca':<16}"
        for lo, hi in _SPEED_BANDS:
            col_hdr += f"{lo}-{hi}mph".center(12)
        print(col_hdr)
        print("  " + "─" * 60)

        # Filas (muescas observadas)
        for n in _NOTCH_ROWS:
            row = f"  {notch_label(n):<16}"
            for b in range(len(_SPEED_BANDS)):
                c = self._count(b, n)
                mark = "✓" if c >= self.target else " "
                cell = f"{min(c, self.target)}/{self.target}{mark}"
                row += cell.center(12)
            print(row)

        print("  " + "─" * 60)
        print(f"  Progreso global: [{_bar(pct)}] {done}/{total}  ({pct*100:.0f}%)")
        print("═" * 64)

        # Estado actual
        atp = "  ⚠ ATP ACTIVO (aprendizaje en pausa)" if self._ack_active else ""
        lim_str = (f"lím={self._cur_limit:.0f} mph"
                   if self._cur_limit else "lím=?")
        accel_str = (f"a={self._cur_accel:+.2f} m/s²" if self._cur_accel is not None
                     else "a=dv/dt")
        print(f"  Ahora: {notch_label(self._cur_notch):<16}  "
              f"spd={self._cur_speed:5.1f} mph   {lim_str}   "
              f"grad={self._cur_grad:+.1f}%   {accel_str}{atp}")
        # Diagnóstico en vivo: por qué (no) se está registrando la muestra
        print(f"  Estado learner: {self.learner.last_reason}   "
              f"(snapshots: {self._snaps})")

        # Captura oportunista (informativo, se adapta a tu conducción)
        print()
        for line in self._hints():
            print(f"  ► {line}")
        print()
        print("  Ctrl+C para terminar.  El progreso ya está guardado en"
              " el perfil del tren.")
        print("═" * 64)


# ── Entrada principal ─────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monitor de aprendizaje guiado — TSW6 autopilot")
    parser.add_argument("--host", default="127.0.0.1",
                        help="IP del RailBridge Companion (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=COMP_PORT)
    parser.add_argument("--vehicle", default=None,
                        help="Nombre del vehículo (override de la detección)")
    parser.add_argument("--target", type=int, default=TARGET_SAMPLES,
                        help=f"Muestras por celda (default: {TARGET_SAMPLES})")
    parser.add_argument("--reset", action="store_true",
                        help="Borra calibration.json y empieza de cero")
    args = parser.parse_args()

    _enable_utf8()

    # Conexión vía TswConnection (misma que el autopilot: gestiona el
    # emparejamiento de dispositivo y la persistencia de deltas, necesarios
    # para recibir el stream completo de telemetría del companion).
    conn = TswConnection()
    print("Buscando RailBridge Companion…")
    for _ in range(30):
        conn.probe()
        if conn.mode == "companion" and conn.comp_base:
            break
        time.sleep(1.0)
    if conn.mode != "companion" or not conn.comp_base:
        print("ERROR: No se pudo conectar al RailBridge Companion.")
        print("       ¿Está activo el botón CMP en RailBridge y TSW6 ejecutándose?")
        sys.exit(1)
    base_url = conn.comp_base
    print(f"Conectado a {base_url}")

    # Nombre del tren: el loco se detecta del propio stream del companion
    # (conn.get_vehicle_name); /vehicles queda como reserva.
    def _detect_name() -> Optional[str]:
        return conn.get_vehicle_name() or get_vehicle_name(base_url)

    # Detectar vehículo (define el perfil donde se guarda la calibración).
    # Si no aparece al arrancar (es habitual el primer momento), seguimos
    # buscándolo en segundo plano mientras se conduce y, al detectarlo,
    # adoptamos su perfil sin perder lo ya capturado.
    if args.vehicle:
        vehicle, vehicle_known = args.vehicle, True
    else:
        detected = _detect_name()
        vehicle = detected or "Desconocido"
        vehicle_known = detected is not None

    profile_path = path_for_vehicle(vehicle)
    print(f"Vehículo: {vehicle}" + ("" if vehicle_known else "  (se seguirá buscando)"))
    print(f"Perfil  : {profile_path}")

    # Reset opcional (sobre el perfil de este tren, no el genérico)
    if args.reset and os.path.exists(profile_path):
        os.remove(profile_path)
        print("Perfil borrado — empezando de cero.")

    learner = OnlineLearner(vehicle=vehicle)
    monitor = LearnMonitor(learner, vehicle, max(1, args.target),
                           vehicle_known=vehicle_known)

    # Búsqueda en segundo plano del nombre del tren (solo si aún no se conoce).
    # get_vehicle_name bloquea ~2 s, por eso corre en un hilo y no en el bucle.
    _detected_name: dict[str, Optional[str]] = {"v": None}
    if not vehicle_known:
        def _search_vehicle() -> None:
            while _detected_name["v"] is None:
                time.sleep(3.0)
                name = _detect_name()
                if name:
                    _detected_name["v"] = name
                    return
        threading.Thread(target=_search_vehicle, daemon=True).start()

    print("Iniciando monitor — conduce manualmente.\n")
    time.sleep(1.0)

    try:
        while True:
            telem = conn.get_telemetry()
            monitor._snaps += 1

            speed = telem.get("speed_mph")
            notch = telem.get("handle_notch")
            grad  = telem.get("gradient_pct") or 0.0
            accel = telem.get("accel_mps2")
            limit = telem.get("limit_mph")
            ack   = bool(telem.get("ack_required", False))

            # Necesitamos al menos velocidad y muesca conocidas para alimentar.
            if speed is None or notch is None:
                monitor.render_waiting(speed)
                time.sleep(0.2)
                continue

            # ¿El hilo de búsqueda encontró el nombre? Adoptar el perfil real
            # fusionando lo capturado hasta ahora; luego deja de buscar.
            if not monitor.vehicle_known and _detected_name["v"]:
                name = _detected_name["v"]
                old_path = learner.save_path
                learner.adopt_profile(name)
                # Borrar el temporal 'Desconocido' (sus datos ya se fusionaron)
                if (old_path != learner.save_path
                        and os.path.basename(old_path) == "Desconocido.json"
                        and os.path.exists(old_path)):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
                monitor.vehicle = name
                monitor.vehicle_known = True
                vehicle = name

            monitor.feed(speed, int(notch), grad, accel, limit, ack)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        learner.save()  # persistir progreso aunque no haya constantes confiables
        _clear()
        done, total = monitor._total_progress()
        consts = learner.get_constants()
        print("═" * 64)
        print("  SESIÓN DE APRENDIZAJE FINALIZADA")
        print("═" * 64)
        print(f"  Vehículo : {vehicle}")
        print(f"  Celdas   : {done}/{total} completas")
        print(f"  Guardado : {learner.save_path}")
        print()
        if consts:
            print("  Constantes aprendidas (confiables):")
            for k, v in consts.items():
                print(f"    {k:22s} = {v:.3f} m/s²")
        else:
            print("  Aún no hay constantes confiables — conduce más tiempo.")
        print("═" * 64)


if __name__ == "__main__":
    main()
