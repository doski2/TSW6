#!/usr/bin/env python3
"""
learn_monitor.py — Monitor de aprendizaje guiado para calibración del tren.

Muestra matrices de objetivos (muesca × banda de velocidad, o 4 ejes en freight),
guía qué capturar y alimenta OnlineLearner / FreightLearner en vivo.
Los perfiles se guardan en logs/profiles/<tren>.json.

Uso:
    aprender.bat
    python learn_monitor.py
    python learn_monitor.py --freight
    python learn_monitor.py --reset
"""

import argparse
import os
import sys
import threading
import time
from typing import Optional

from control_layout import detect_control_layout
from train_labels import (
    COMP_PORT, FREIGHT_AXIS_ROWS, control_level_label, control_value_label,
    get_vehicle_name, notch_label,
)
from tsw_connection import TswConnection
from online_learner import (
    OnlineLearner, path_for_vehicle, _SPEED_BANDS, _speed_band_index,
    MIN_SPEED, MIN_SPEED_FREIGHT,
)
from freight_learner import (
    FreightLearner, create_learner, freight_quantize_level,
    infer_active_axis, resolve_feed_axis,
)

_AXIS_HINT = {
    "throttle":    "tracción",
    "train_brake": "freno automático",
    "ind_brake":   "freno independiente",
    "dyn_brake":   "freno dinámico",
}

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


def _resolve_vehicle_name(vehicle: str, conn: TswConnection,
                          detected: Optional[str]) -> str:
    """Nombre del loco para perfil/learner (stream, API o detección en hilo)."""
    if vehicle and vehicle.strip() and vehicle != "Desconocido":
        return vehicle.strip()
    from_stream = conn.get_vehicle_name()
    if from_stream:
        return from_stream
    if detected:
        return detected
    return vehicle or "Desconocido"


def _ensure_freight_learner(learner, vehicle: str, conn: TswConnection,
                            detected: Optional[str], min_speed: float):
    """Sustituye OnlineLearner por FreightLearner si el tren es freight_na."""
    veh = _resolve_vehicle_name(vehicle, conn, detected)
    if isinstance(learner, FreightLearner):
        _adopt_vehicle_profile(learner, veh)
        return learner, veh
    new = create_learner(vehicle=veh, layout="freight_na", min_speed=min_speed)
    if isinstance(new, FreightLearner):
        _adopt_vehicle_profile(new, veh)
        return new, veh
    return learner, vehicle


def _adopt_vehicle_profile(learner, vehicle: str) -> None:
    """Mueve el perfil de Desconocido.json al nombre real del loco."""
    if not vehicle or vehicle == "Desconocido":
        return
    new_path = path_for_vehicle(vehicle)
    if learner.save_path == new_path:
        return
    old_path = learner.save_path
    learner.adopt_profile(vehicle)
    if (os.path.basename(old_path) == "Desconocido.json"
            and os.path.exists(old_path)
            and old_path != learner.save_path):
        try:
            os.remove(old_path)
        except OSError:
            pass


def _sync_vehicle_from_telem(vehicle: str, conn: TswConnection,
                             detected: Optional[str],
                             telem: dict) -> str:
    """Nombre del loco: argumento, stream SSE o telemetría enriquecida."""
    name = _resolve_vehicle_name(vehicle, conn, detected)
    stream_name = telem.get("vehicle_name")
    if stream_name and str(stream_name).strip():
        return str(stream_name).strip()
    return name


class LearnMonitor:
    """Dashboard guiado sobre el conteo de muestras del learner."""

    def __init__(self, learner, vehicle: str, target: int,
                 vehicle_known: bool = True, layout: str = "combined"):
        self.learner = learner
        self.vehicle = vehicle
        self.target = target
        self.vehicle_known = vehicle_known
        self.layout = layout

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
        self._cur_controls: dict = {}
        self._cur_axis: Optional[str] = None
        self._cur_level: Optional[float] = None
        self._learner_mismatch = False

    @property
    def _is_freight(self) -> bool:
        return (self.layout == "freight_na"
                or isinstance(self.learner, FreightLearner))

    # ── Conteo de muestras por celda (lee el estado interno del learner) ──────

    def _count(self, band: int, notch: int) -> int:
        return self.learner._n_bands[band].get(notch, 0)

    def _count_freight(self, axis: str, band: int, level: int) -> int:
        if isinstance(self.learner, FreightLearner):
            return self.learner.band_count(axis, band, level)
        return 0

    def _is_complete(self, band: int, notch: int) -> bool:
        return self._count(band, notch) >= self.target

    def _is_complete_freight(self, axis: str, band: int, level: int) -> bool:
        return self._count_freight(axis, band, level) >= self.target

    def _total_progress(self) -> tuple[int, int]:
        if self._is_freight:
            done = total = 0
            for axis, (_, rows) in FREIGHT_AXIS_ROWS.items():
                for lv in rows:
                    for b in range(len(_SPEED_BANDS)):
                        total += 1
                        if self._is_complete_freight(axis, b, lv):
                            done += 1
            return done, total
        done = sum(
            1 for b in range(len(_SPEED_BANDS)) for n in _NOTCH_ROWS
            if self._is_complete(b, n)
        )
        total = len(_SPEED_BANDS) * len(_NOTCH_ROWS)
        return done, total

    def render_waiting(self, speed: Optional[float]) -> None:
        """Pantalla de espera hasta conocer mandos o velocidad."""
        now = time.time()
        if now - self._last_render < 0.5:
            return
        self._last_render = now
        _clear()
        print("═" * 64)
        print(f"  MONITOR DE APRENDIZAJE   ·   {self.vehicle}")
        print("═" * 64)
        spd = f"{speed:.1f} mph" if speed is not None else "?"
        if self._is_freight:
            print(f"  Esperando telemetría de mandos…   (velocidad: {spd})")
            print()
            print("  El companion envía posiciones al CAMBIAR un mando.")
            print("  ► Mueve tracción o algún freno para que se detecte.")
        else:
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

    def feed_freight(self, speed: float, grad: float,
                     accel: Optional[float], limit: Optional[float],
                     ack: bool, controls: dict,
                     axis: Optional[str], level: Optional[float]) -> None:
        """Alimenta FreightLearner cuando se detecta un eje activo."""
        self._cur_speed = speed
        self._cur_notch = int(controls.get("throttle") or 0)
        self._cur_grad = grad
        self._cur_band = _speed_band_index(speed)
        self._cur_limit = limit
        self._cur_accel = accel
        self._cur_controls = dict(controls)
        self._cur_axis = axis
        self._cur_level = level
        self._ack_active = ack

        if not ack and axis and level is not None:
            if isinstance(self.learner, FreightLearner):
                self._learner_mismatch = False
                self.learner.feed(axis, level, speed, grad, accel, controls)
            else:
                self._learner_mismatch = True

        now = time.time()
        if now - self._last_save >= 5.0:
            self._last_save = now
            self.learner.save()
        if now - self._last_render >= 0.5:
            self._last_render = now
            self.render()

    # ── Captura oportunista (se adapta a ti, no al revés) ─────────────────────

    def _pending_in_band(self, band: int) -> list[int]:
        return [n for n in _NOTCH_ROWS if not self._is_complete(band, n)]

    def _pending_freight_in_band(self, axis: str, band: int) -> list[int]:
        _, rows = FREIGHT_AXIS_ROWS[axis]
        return [lv for lv in rows if not self._is_complete_freight(axis, band, lv)]

    def _freight_active_level(self, axis: str) -> Optional[int]:
        if axis == "throttle":
            v = self._cur_controls.get("throttle")
        else:
            v = self._cur_controls.get(axis)
        if v is None:
            return None
        return freight_quantize_level(axis, float(v))

    def _hints(self) -> list[str]:
        if self._is_freight:
            return self._hints_freight()
        return self._hints_combined()

    def _hints_combined(self) -> list[str]:
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

    def _hints_freight(self) -> list[str]:
        band = self._cur_band
        lo, hi = _SPEED_BANDS[band]
        lines: list[str] = []

        active = self._cur_axis or (
            isinstance(self.learner, FreightLearner) and self.learner.last_axis)
        if active and active in FREIGHT_AXIS_ROWS:
            lv = self._freight_active_level(active)
            if lv is not None and lv in FREIGHT_AXIS_ROWS[active][1]:
                if not self._is_complete_freight(active, band, lv):
                    need = self.target - self._count_freight(active, band, lv)
                    lines.append(
                        f"Capturando {_AXIS_HINT[active]} "
                        f"{control_level_label(active, lv)} @ {lo}-{hi} mph "
                        f"→ mantén ~2 s  (faltan {need})")

        for axis, (_, rows) in FREIGHT_AXIS_ROWS.items():
            pending = self._pending_freight_in_band(axis, band)
            if not pending:
                continue
            labels = ", ".join(control_level_label(axis, lv) for lv in pending[:4])
            extra = f" +{len(pending) - 4}" if len(pending) > 4 else ""
            lines.append(
                f"Pendiente {_AXIS_HINT[axis]} @ {lo}-{hi} mph: {labels}{extra}")

        if not lines:
            done, total = self._total_progress()
            if done >= total:
                return ["¡Todas las celdas completas! El tren está calibrado."]
            return [f"Banda {lo}-{hi} mph completa en todos los ejes. "
                    "Conduce a otra velocidad para seguir capturando."]

        if abs(self._cur_grad) > 2.0:
            lines.append(
                f"Pendiente fuerte ({self._cur_grad:+.1f}%): prioriza freno dinámico "
                "o train brake; evita calibrar tracción (>2%).")
        elif abs(self._cur_grad) > 0.5:
            lines.append(
                f"Pendiente suave ({self._cur_grad:+.1f}%): se compensa; "
                "llano es más preciso pero puedes capturar.")
        elif self._cur_speed > 5:
            lines.append(
                "Sugerencia: un solo mando estable ~2 s; no muevas otros ejes "
                "mientras captura.")

        lines.append("Orden recomendado: tracción → freno auto → dyn → freno ind.")
        return lines

    # ── Render ────────────────────────────────────────────────────────────────

    def render(self) -> None:
        if self._is_freight:
            self._render_freight()
        else:
            self._render_combined()

    def _render_matrix_block(self, title: str, axis: str,
                             rows: tuple[int, ...]) -> None:
        col_hdr = f"  {'Nivel':<14}"
        for lo, hi in _SPEED_BANDS:
            col_hdr += f"{lo}-{hi}".center(10)
        print(f"  {title}")
        print(col_hdr)
        for lv in rows:
            row = f"  {control_level_label(axis, lv):<14}"
            for b in range(len(_SPEED_BANDS)):
                c = self._count_freight(axis, b, lv)
                mark = "✓" if c >= self.target else "·"
                cell = f"{min(c, self.target)}/{self.target}{mark}"
                row += cell.center(10)
            print(row)
        print()

    def _render_freight(self) -> None:
        _clear()
        done, total = self._total_progress()
        pct = done / total if total else 0.0

        veh_str = self.vehicle
        if not self.vehicle_known:
            veh_str += "  (buscando nombre…)"
        print("═" * 64)
        print(f"  MONITOR FREIGHT NA (multi-mando)   ·   {veh_str}")
        print(f"  Un mando estable ~2 s por captura  ·  objetivo: {self.target}/celda")
        print(f"  Perfil: {os.path.basename(self.learner.save_path)}")
        print("═" * 64)

        for axis, (title, rows) in FREIGHT_AXIS_ROWS.items():
            self._render_matrix_block(title, axis, rows)

        print("  " + "─" * 60)
        print(f"  Progreso global: [{_bar(pct)}] {done}/{total}  ({pct*100:.0f}%)")
        print("═" * 64)

        atp = "  ⚠ ATP ACTIVO (aprendizaje en pausa)" if self._ack_active else ""
        lim_str = (f"lím={self._cur_limit:.0f} mph"
                   if self._cur_limit else "lím=?")
        accel_str = (f"a={self._cur_accel:+.2f} m/s²" if self._cur_accel is not None
                     else "a=dv/dt")
        ctrl = self._cur_controls
        mandos = (f"thr={control_value_label('throttle', ctrl.get('throttle'))}  "
                  f"auto={control_value_label('train_brake', ctrl.get('train_brake'))}  "
                  f"ind={control_value_label('ind_brake', ctrl.get('ind_brake'))}  "
                  f"dyn={control_value_label('dyn_brake', ctrl.get('dyn_brake'))}")
        print(f"  Mandos: {mandos}")
        print(f"  Vel={self._cur_speed:5.1f} mph   {lim_str}   "
              f"grad={self._cur_grad:+.1f}%   {accel_str}{atp}")

        axis_hint = ""
        if self._learner_mismatch:
            axis_hint = "⚠ learner UK en tren freight — reinicia aprender.bat   "
        elif isinstance(self.learner, FreightLearner):
            if self._cur_axis:
                axis_hint = f"eje activo={_AXIS_HINT.get(self._cur_axis, self._cur_axis)}   "
            elif self.learner.last_axis:
                axis_hint = f"último eje={_AXIS_HINT.get(self.learner.last_axis, self.learner.last_axis)}   "
        reason = self.learner.last_reason
        if self._learner_mismatch:
            reason = "learner incorrecto (perfil UK) — reinicia aprender.bat"
        print(f"  Estado learner: {reason}   {axis_hint}"
              f"(snapshots: {self._snaps})")

        print()
        for line in self._hints():
            print(f"  ► {line}")
        print()
        print("  Ctrl+C para terminar.  Progreso guardado en el perfil del tren.")
        print("═" * 64)

    def _render_combined(self) -> None:
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
        axis_hint = ""
        if isinstance(self.learner, FreightLearner) and self.learner.last_axis:
            axis_hint = f"eje={self.learner.last_axis}   "
        print(f"  Estado learner: {self.learner.last_reason}   {axis_hint}"
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
                        help="Borra el perfil del tren y empieza de cero")
    parser.add_argument("--freight", action="store_true",
                        help=f"Modo mercancías: velocidad mínima {MIN_SPEED_FREIGHT:.0f} mph "
                             f"(por defecto {MIN_SPEED:.0f} mph para pasajeros)")
    parser.add_argument("--min-speed", type=float, default=None, metavar="MPH",
                        help="Velocidad mínima personalizada (mph) para aceptar muestras")
    args = parser.parse_args()

    if args.min_speed is not None:
        min_speed = max(0.5, args.min_speed)
    elif args.freight:
        min_speed = MIN_SPEED_FREIGHT
    else:
        min_speed = MIN_SPEED

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

    init_layout_hint: Optional[str] = "freight_na" if args.freight else None
    if init_layout_hint is None and vehicle_known:
        if detect_control_layout(vehicle) == "freight_na":
            init_layout_hint = "freight_na"

    learner = create_learner(vehicle=vehicle, min_speed=min_speed,
                             layout=init_layout_hint)
    init_layout = "freight_na" if isinstance(learner, FreightLearner) else "combined"
    monitor = LearnMonitor(learner, vehicle, max(1, args.target),
                           vehicle_known=vehicle_known, layout=init_layout)
    prev_controls: Optional[dict] = None
    capture_axis: Optional[str] = None
    capture_level: Optional[float] = None

    modo_vel = "mercancías" if min_speed <= MIN_SPEED_FREIGHT else "pasajeros"
    print(f"Vel. mín. : {min_speed:.0f} mph ({modo_vel})")

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

            layout = telem.get("control_layout", "combined")
            resolved_vehicle = _sync_vehicle_from_telem(
                vehicle, conn, _detected_name["v"], telem)
            if resolved_vehicle and resolved_vehicle != "Desconocido":
                _adopt_vehicle_profile(learner, resolved_vehicle)
                vehicle = resolved_vehicle
                monitor.vehicle = resolved_vehicle
                monitor.vehicle_known = True

            is_freight = isinstance(learner, FreightLearner) or layout == "freight_na"
            monitor.layout = "freight_na" if is_freight else "combined"

            if speed is None:
                monitor.render_waiting(speed)
                time.sleep(0.2)
                continue

            if not is_freight and notch is None:
                monitor.render_waiting(speed)
                time.sleep(0.2)
                continue

            # ¿El hilo de búsqueda encontró el nombre? Adoptar el perfil real
            # fusionando lo capturado hasta ahora; luego deja de buscar.
            if not monitor.vehicle_known and _detected_name["v"]:
                name = _detected_name["v"]
                _adopt_vehicle_profile(learner, name)
                monitor.vehicle = name
                monitor.vehicle_known = True
                vehicle = name
                monitor.layout = ("freight_na" if isinstance(learner, FreightLearner)
                                  else "combined")

            if layout == "freight_na" and not isinstance(learner, FreightLearner):
                learner, veh_resolved = _ensure_freight_learner(
                    learner, vehicle, conn, _detected_name["v"], min_speed)
                monitor.learner = learner
                monitor._learner_mismatch = False
                if veh_resolved and veh_resolved != "Desconocido":
                    vehicle = veh_resolved
                    monitor.vehicle = veh_resolved
                    monitor.vehicle_known = True

            if is_freight:
                controls = {
                    "throttle": float(notch if notch is not None else 0),
                    "train_brake": float(telem.get("train_brake_value") or 0.0),
                    "ind_brake": float(telem.get("ind_brake_value") or 0.0),
                    "dyn_brake": float(telem.get("dyn_brake_value") or 0.0),
                }
                axis, level, capture_axis, capture_level = resolve_feed_axis(
                    prev_controls, controls, capture_axis, capture_level)
                monitor.feed_freight(speed, grad, accel, limit, ack, controls, axis, level)
                prev_controls = controls
            else:
                assert notch is not None
                monitor.feed(speed, notch, grad, accel, limit, ack)
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
