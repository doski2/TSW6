#!/usr/bin/env python3
"""
profiler.py — Calibrador pasivo de constantes físicas del tren.

Escucha el SSE de RailBridge mientras conduces manualmente y extrae
eventos de frenado/tracción/inercia para calcular:
  MAX_DECEL_MS2, TARGET_ACCEL_MS2, TARGET_DECEL_MS2, COAST_DECEL_MS2

Todos los eventos se registran; se promedian los "limpios" (notch estable
≥ MIN_EVENT_S y cambio de velocidad ≥ MIN_SPEED_CHANGE_MPH).
Los outliers (>2σ) se excluyen del promedio pero se conservan en el CSV.

Uso:
    python profiler.py
    python profiler.py --host 192.168.1.5 --vehicle "Class 323"
    python profiler.py --output logs/calib/
"""

import argparse
import csv
import json
import os
import socket
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

# ── Configuración del companion ───────────────────────────────────────────────

COMP_PORT  = 51160
COMP_TOKEN = "aaeeb63be194470bb7f97c98b93635aa"
KPH_TO_MPH = 0.621371

# ── Parámetros de filtrado de eventos ────────────────────────────────────────

MIN_EVENT_S         = 3.0   # duración mínima para aceptar un evento
MIN_SPEED_CHANGE    = 0.8   # mph mínimo de cambio de velocidad
GRAD_BAND_WIDTH     = 0.5   # ancho de banda de gradiente (%)

# ── Constantes actuales del speed_governor (para comparar en el resumen) ─────

CURRENT_CONSTANTS = {
    "MAX_DECEL_MS2":    1.071,
    "TARGET_ACCEL_MS2": 0.298,
    "TARGET_DECEL_MS2": 0.433,
    "COAST_DECEL_MS2":  0.095,
}

# ── Clasificación de vehículos ────────────────────────────────────────────────

VEHICLE_TYPES: dict[str, str] = {
    "class 323":  "passenger-suburban",
    "class 387":  "passenger-suburban",
    "class 350":  "passenger-suburban",
    "class 390":  "passenger-intercity",
    "class 221":  "passenger-intercity",
    "class 220":  "passenger-intercity",
    "class 158":  "passenger-regional",
    "class 170":  "passenger-regional",
    "class 153":  "passenger-regional",
    "class 156":  "passenger-regional",
    "class 66":   "freight",
    "class 70":   "freight",
    "class 37":   "freight",
    "class 47":   "freight",
    "sd40":       "freight-na",
    "sd70":       "freight-na",
    "es44":       "freight-na",
    "gp38":       "freight-na",
    "bnsf":       "freight-na",
}

NOTCH_LABELS: dict[int, str] = {
    0: "Freno-4(max)",
    1: "Freno-3",
    2: "Freno-2",
    3: "Freno-1",
    4: "Neutro",
    5: "Tracción-1",
    6: "Tracción-2",
    7: "Tracción-3",
    8: "Tracción-4(max)",
}


# ── Funciones auxiliares ──────────────────────────────────────────────────────

def classify_vehicle(name: str) -> str:
    n = name.lower()
    for key, vtype in VEHICLE_TYPES.items():
        if key in n:
            return vtype
    return "unknown"


def grad_band_label(g: float) -> str:
    """Normaliza el gradiente a la banda más cercana: '+0.5%', '-1.0%', etc."""
    band = round(g / GRAD_BAND_WIDTH) * GRAD_BAND_WIDTH
    if abs(band) < 1e-9:
        return "+0.0%"    # evitar '-0.0%'
    return f"{band:+.1f}%"


def notch_label(n: int) -> str:
    return NOTCH_LABELS.get(n, f"Notch-{n}")


# Filas de matriz freight_na (niveles cuantizados que el learner observa)
FREIGHT_AXIS_ROWS: dict[str, tuple[str, tuple[int, ...]]] = {
    "throttle":    ("TRACCIÓN",            (1, 2, 3, 4, 5, 6, 7, 8)),
    "train_brake": ("FRENO AUTOMÁTICO",    (2, 3, 4, 5, 6, 7, 8, 9, 10)),
    "ind_brake":   ("FRENO INDEPENDIENTE", (-8, -6, -4, -2, 2, 4, 6, 8)),
    "dyn_brake":   ("FRENO DINÁMICO",      (1, 2, 3, 4, 5, 6, 7, 8)),
}


def control_level_label(axis: str, level: int) -> str:
    """Etiqueta de fila en la matriz de calibración freight_na."""
    if axis == "throttle":
        return "Idle" if level == 0 else f"N{level}"
    if axis == "train_brake":
        return f"{level * 10}%"
    if axis == "ind_brake":
        if level == 0:
            return "0%"
        return f"{level * 10:+d}%"
    if axis == "dyn_brake":
        return "Off" if level == 0 else f"D{level}"
    return str(level)


def control_value_label(axis: str, value: Optional[float]) -> str:
    """Etiqueta del valor actual de telemetría (cabecera freight)."""
    if value is None:
        return "?"
    if axis == "throttle":
        return f"N{int(round(value))}"
    if axis == "train_brake":
        return f"{max(0.0, value) * 100:.0f}%"
    if axis == "ind_brake":
        return f"{value * 100:+.0f}%"
    if axis == "dyn_brake":
        return "Off" if value < 0.02 else f"D{int(round(value * 8))}"
    return f"{value:.2f}"


# ── Estructuras de datos ──────────────────────────────────────────────────────

@dataclass
class Sample:
    t:                float           # timestamp Unix
    speed:            float           # mph
    notch:            int             # 0-8 (handle combinado)
    grad:             float           # % (positivo = subida)
    accel:            Optional[float] # m/s² nativo de la API (puede ser None)
    next_stop:        Optional[str]   = None  # nombre de la próxima parada
    next_stop_dist:   Optional[float] = None  # distancia a la próxima parada (m)
    next_stop_plat_m: Optional[float] = None  # longitud del andén (m)
    limit_mph:        Optional[float] = None  # límite de velocidad activo (mph)
    service:          Optional[str]   = None  # nombre del servicio/trayecto


@dataclass
class CalibEvent:
    notch:     int
    t_start:   float
    t_end:     float
    v_start:   float           # mph
    v_end:     float           # mph
    grad_avg:  float           # % promedio
    accel_dv:  float           # m/s² calculado como Δv/Δt
    accel_api: Optional[float] # m/s² promedio de la API (si disponible)
    dist_m:    float           = 0.0   # distancia recorrida durante el evento (m)
    next_stop: Optional[str]   = None  # parada que se aproximaba al cerrar el evento
    corrupt:   bool            = False # True = invalidado por ATP u otra anomalía


@dataclass
class StopEvent:
    """Registro de una parada en andén."""
    station_name:      str
    odo_m:             float
    platform_length_m: Optional[float]
    dwell_s:           float
    braking_dist_m:    float
    approach_v_mph:    float
    approach_grad_pct: float
    service:           Optional[str]


# ── Conexión al companion ─────────────────────────────────────────────────────

def find_companion(host: str, port: int) -> Optional[str]:
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect((host, port))
        s.close()
        return f"http://{host}:{port}"
    except OSError:
        return None


def get_vehicle_name(base_url: str) -> Optional[str]:
    """Intenta leer el nombre del vehículo desde /vehicles."""
    try:
        r = requests.get(
            f"{base_url}/vehicles",
            headers={"Authorization": f"Bearer {COMP_TOKEN}"},
            timeout=2,
        )
        if r.status_code == 200:
            vehicles = r.json()
            if isinstance(vehicles, list) and vehicles:
                v = vehicles[0]
                name = v.get("name") or v.get("displayName") or v.get("className")
                if name and str(name).strip().lower() not in ("none", ""):
                    return str(name).strip()
    except Exception:
        pass
    return None


def sse_stream(base_url: str):
    """Generador: yield de tuplas (event_type, data) desde el SSE con reconexión automática."""
    url = f"{base_url}/events?t={COMP_TOKEN}"
    while True:
        try:
            with requests.get(url, stream=True, timeout=(3, None)) as r:
                event_type = None
                for raw in r.iter_lines(decode_unicode=True):
                    if isinstance(raw, str) and raw:
                        if raw.startswith("event:"):
                            event_type = raw[6:].strip()
                        elif raw.startswith("data:") and event_type in (
                            "dmi_snapshot", "dashboard_snapshot", "companion_dmi_delta"
                        ):
                            try:
                                yield event_type, json.loads(raw[5:].strip())
                            except json.JSONDecodeError:
                                pass
                    else:
                        event_type = None
        except Exception:
            time.sleep(1)


def parse_snapshot(data: dict) -> Optional[Sample]:
    """Extrae campos del dmi_snapshot. Devuelve None si faltan campos clave."""
    def _v(*path):
        obj = data
        for k in path:
            if not isinstance(obj, dict) or k not in obj:
                return None
            obj = obj[k]
        return float(obj) if isinstance(obj, (int, float)) else None

    def _sv(raw) -> Optional[float]:
        """Extrae valor numérico de campo de estación (dict.value o directo)."""
        if raw is None:
            return None
        val = raw.get("value") if isinstance(raw, dict) else raw
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    speed_kph = _v("speed", "kph")
    raw_notch = _v("controls", "throttle_notch", "value")
    if speed_kph is None or raw_notch is None:
        return None

    # Límite de velocidad activo (kph → mph)
    limit_kph = _v("limits", "current_permitted_speed_kph", "value")
    limit_mph = limit_kph * KPH_TO_MPH if limit_kph is not None else None

    # Próxima parada, distancia y longitud de andén
    next_stop:        Optional[str]   = None
    next_stop_dist:   Optional[float] = None
    next_stop_plat_m: Optional[float] = None
    raw_stations = data.get("planning", {}).get("stations", []) or []
    if raw_stations:
        s = raw_stations[0]
        name_raw = s.get("name") or s.get("station_name") or s.get("id")
        if isinstance(name_raw, dict):
            name_raw = name_raw.get("value")
        if name_raw:
            next_stop = str(name_raw)
        dist_raw = (_sv(s.get("distance_stop_m")) or _sv(s.get("distance_end_m"))
                    or _sv(s.get("distance_m"))    or _sv(s.get("distance_start_m")))
        if dist_raw is not None and dist_raw > 0:
            next_stop_dist = dist_raw
        plat_raw = _sv(s.get("platform_length_m")) or _sv(s.get("platform_length"))
        if plat_raw is not None and plat_raw > 0:
            next_stop_plat_m = plat_raw

    # Nombre del servicio
    service: Optional[str] = (
        data.get("identity", {}).get("service_name", {}).get("value")
        or data.get("identity", {}).get("train_identifier", {}).get("value")
    )

    return Sample(
        t                = time.time(),
        speed            = speed_kph * KPH_TO_MPH,
        notch            = int(raw_notch),
        grad             = _v("planning", "gradient_percent", "value") or 0.0,
        accel            = _v("motion", "acceleration_mps2", "value"),
        next_stop        = next_stop,
        next_stop_dist   = next_stop_dist,
        next_stop_plat_m = next_stop_plat_m,
        limit_mph        = limit_mph,
        service          = service or None,
    )


def parse_doors(data: dict) -> bool:
    """Extrae estado de puertas de un dashboard_snapshot."""
    try:
        doors = (data.get("feed", {})
                     .get("typed", {})
                     .get("controls", {})
                     .get("passenger_doors", []))
        return any(
            isinstance(d, dict)
            and isinstance(d.get("value"), dict)
            and d["value"].get("is_open") is True
            for d in doors
        )
    except Exception:
        return False


def parse_route_stations(data: dict) -> list:
    """
    Extrae paradas con nombre real desde dashboard_snapshot.
    Ruta: feed.typed.route.route_markers (kind='Platform').
    Devuelve lista de {name, distance_m, platform_length_m?} ordenada por distancia.
    """
    try:
        route = (data.get("feed", {})
                     .get("typed", {})
                     .get("route", {}))
        raw_markers = route.get("route_markers", {}).get("value") or []
        stations: list[dict] = []
        for m in raw_markers:
            if not isinstance(m, dict) or m.get("kind") != "Platform":
                continue
            dist = m.get("distance_m")
            if dist is None or float(dist) <= 0:
                continue
            name = m.get("label") or ""
            if not name or str(name).strip().lower() in ("none", ""):
                continue
            entry: dict = {"name": str(name).strip(), "distance_m": float(dist)}
            plat = m.get("platform_length_m")
            if plat and float(plat) > 0:
                entry["platform_length_m"] = round(float(plat), 1)
            stations.append(entry)
        stations.sort(key=lambda x: x["distance_m"])
        return stations
    except Exception:
        return []


# ── Lógica de calibración ─────────────────────────────────────────────────────

class Profiler:

    def __init__(self, vehicle_name: str, output_dir: str = "logs"):
        self.vehicle_name = vehicle_name
        self.vehicle_type = classify_vehicle(vehicle_name)
        self.output_dir   = output_dir
        self.events: list[CalibEvent] = []
        self.stops:  list[StopEvent]  = []

        self._cur_notch: Optional[int]      = None
        self._event_samples: list[Sample]   = []
        self._last_print = 0.0

        # Odómetro (integración trapezoidal de v*dt)
        self._odo_m:  float           = 0.0
        self._last_t: Optional[float] = None
        self._last_v: float           = 0.0      # mph, para integración trapezoidal

        # Seguimiento de paradas
        self._doors_open:     bool            = False
        self._stop_start_t:   Optional[float] = None   # t cuando abrieron puertas
        self._stop_name:      Optional[str]   = None   # nombre de la parada actual
        self._stop_plat_m:    Optional[float] = None
        self._stop_odo_m:     float           = 0.0
        self._approach_event: Optional[CalibEvent] = None
        self._last_service:   Optional[str]   = None

        # Seguimiento de límites de velocidad
        self._limit_log:  list[tuple[float, float]] = []   # (odo_m, limit_mph)
        self._last_limit: Optional[float] = None

        # Estado ATP / ack_required
        self._ack_active: bool = False

        os.makedirs(output_dir, exist_ok=True)

        print(f"\n  Vehículo : {vehicle_name}  ({self.vehicle_type})")
        print(f"  Salida   : {output_dir}/")
        print("  Conduciendo manualmente — Ctrl+C para finalizar y ver informe.\n")

    # ── Alimentar muestras ───────────────────────────────────────────────────

    def feed(self, sample: Sample, corrupt: bool = False) -> None:
        """Procesa una muestra; detecta cambios de notch para cerrar/abrir eventos."""
        # ── Odómetro (integración trapezoidal) ───────────────────────────────
        if self._last_t is not None:
            dt = sample.t - self._last_t
            if 0 < dt < 5.0:   # ignorar gaps grandes por reconexión
                v_avg_ms = (self._last_v + sample.speed) / 2.0 * 0.44704
                self._odo_m += v_avg_ms * dt
        self._last_t = sample.t
        self._last_v = sample.speed

        # ── Servicio ─────────────────────────────────────────────────────────
        if sample.service:
            self._last_service = sample.service

        # ── Cambio de límite de velocidad ────────────────────────────────────
        if sample.limit_mph is not None and sample.limit_mph != self._last_limit:
            self._limit_log.append((self._odo_m, sample.limit_mph))
            self._last_limit = sample.limit_mph

        # ── Detección de llegada a parada ────────────────────────────────────
        at_platform = (
            sample.next_stop_dist is not None
            and sample.next_stop_dist < 50.0
            and sample.speed < 2.0
        )
        if at_platform and self._stop_name is None:
            self._stop_name   = sample.next_stop
            self._stop_odo_m  = self._odo_m
            self._stop_plat_m = sample.next_stop_plat_m
            brake_events = [e for e in self.events if e.notch <= 3 and not e.corrupt]
            self._approach_event = brake_events[-1] if brake_events else None

        # ── ATP / ack_required ───────────────────────────────────────────────
        if corrupt:
            if not self._ack_active:
                # Flanco de subida: invalidar evento en curso y últimos 3
                self._event_samples.clear()
                for ev in self.events[-3:]:
                    ev.corrupt = True
                self._ack_active = True
                self._cur_notch  = None
        else:
            if self._ack_active:
                # Flanco de bajada: ATP desaparecido, reiniciar seguimiento
                self._ack_active = False
                self._cur_notch  = None

        # ── Notch y muestras (solo sin ATP activo) ───────────────────────────
        if not self._ack_active:
            if self._cur_notch != sample.notch:
                # Notch cambió: intentar cerrar el evento anterior
                if self._cur_notch is not None and self._event_samples:
                    self._close_event()
                self._cur_notch     = sample.notch
                self._event_samples = [sample]
            else:
                self._event_samples.append(sample)

        # ── Mostrar estado en pantalla cada 2 s ──────────────────────────────
        if time.time() - self._last_print >= 2.0:
            self._last_print = time.time()
            n_ok     = sum(1 for e in self.events if not e.corrupt)
            stop_str = (f"→ {sample.next_stop[:18]}" if sample.next_stop else "")
            atp_str  = "  [ATP]" if self._ack_active else ""
            print(
                f"\r  {notch_label(sample.notch):18s}  "
                f"spd={sample.speed:5.1f} mph  "
                f"grad={sample.grad:+.1f}%  "
                f"odo={self._odo_m/1000:.2f}km  "
                f"ev={n_ok}  {stop_str:22s}{atp_str}  ",
                end="", flush=True,
            )

    def mark_corrupt(self) -> None:
        """Invalida el evento en curso (ATP emergencia, cambio abrupto, etc.)."""
        self._event_samples.clear()
        # Marcar también los últimos eventos cerrados por si ya se registraron
        for ev in self.events[-3:]:
            ev.corrupt = True

    def feed_doors(self, doors_open: bool) -> None:
        """Recibe el estado de puertas del dashboard_snapshot."""
        if doors_open and not self._doors_open:
            # Puertas acaban de abrirse: iniciar registro de permanencia
            self._stop_start_t = time.time()
        elif not doors_open and self._doors_open and self._stop_start_t is not None:
            # Puertas acaban de cerrarse: registrar parada completa
            dwell_s = time.time() - self._stop_start_t
            ev = self._approach_event
            stop = StopEvent(
                station_name      = self._stop_name or "?",
                odo_m             = self._stop_odo_m,
                platform_length_m = self._stop_plat_m,
                dwell_s           = round(dwell_s, 1),
                braking_dist_m    = round(ev.dist_m, 0) if ev else 0.0,
                approach_v_mph    = round(ev.v_start, 1) if ev else 0.0,
                approach_grad_pct = round(ev.grad_avg, 2) if ev else 0.0,
                service           = self._last_service,
            )
            self.stops.append(stop)
            print(
                f"\n  \u2605 PARADA  {stop.station_name}  "
                f"dwell={dwell_s:.0f}s  odo={self._stop_odo_m/1000:.2f}km"
            )
            # Resetear estado de parada
            self._stop_name      = None
            self._stop_start_t   = None
            self._approach_event = None
        self._doors_open = doors_open

    # ── Cierre de un evento ──────────────────────────────────────────────────

    def _close_event(self) -> None:
        if self._cur_notch is None:
            return
        samples = self._event_samples
        if len(samples) < 2:
            return

        t0, t1 = samples[0].t, samples[-1].t
        dt = t1 - t0
        if dt < MIN_EVENT_S:
            return  # evento demasiado corto

        v0, v1 = samples[0].speed, samples[-1].speed
        if abs(v1 - v0) < MIN_SPEED_CHANGE:
            return  # sin cambio apreciable de velocidad

        # Aceleración calculada por Δv/Δt
        accel_dv = (v1 - v0) * 0.44704 / dt   # mph/s → m/s²

        # Gradiente promedio del evento
        grad_avg = sum(s.grad for s in samples) / len(samples)

        # Promedio de la aceleración nativa de la API (más precisa si disponible)
        api_vals  = [s.accel for s in samples if s.accel is not None]
        accel_api = sum(api_vals) / len(api_vals) if api_vals else None

        # Distancia recorrida: integración trapezoidal
        dist_m = 0.0
        for i in range(len(samples) - 1):
            v_avg  = (samples[i].speed + samples[i+1].speed) / 2.0 * 0.44704
            dt_seg = samples[i+1].t - samples[i].t
            if 0 < dt_seg < 2.0:
                dist_m += v_avg * dt_seg

        self.events.append(CalibEvent(
            notch     = self._cur_notch,
            t_start   = t0,
            t_end     = t1,
            v_start   = v0,
            v_end     = v1,
            grad_avg  = grad_avg,
            accel_dv  = accel_dv,
            accel_api = accel_api,
            dist_m    = round(dist_m, 1),
            next_stop = samples[-1].next_stop,
        ))

    # ── Resumen y guardado ───────────────────────────────────────────────────

    def summarize(self) -> None:
        # Cerrar el evento en curso si lo hay
        if self._event_samples:
            self._close_event()

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_events_path = os.path.join(self.output_dir, f"calibration_{ts}.csv")
        csv_stops_path  = os.path.join(self.output_dir, f"calibration_stops_{ts}.csv")
        csv_limits_path = os.path.join(self.output_dir, f"calibration_limits_{ts}.csv")
        txt_path        = os.path.join(self.output_dir, f"calibration_summary_{ts}.txt")

        clean = [e for e in self.events if not e.corrupt]
        print(f"\n\n  Total eventos: {len(self.events)}  |  válidos: {len(clean)}")
        if not clean:
            print("  Sin datos suficientes para calibrar.")
            return

        # ── CSV: eventos de calibración ───────────────────────────────────────
        with open(csv_events_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "vehicle", "vehicle_type", "notch", "notch_label",
                "t_start", "duration_s",
                "v_start_mph", "v_end_mph", "dv_mph",
                "accel_dv_ms2", "accel_api_ms2",
                "grad_avg_pct", "grad_band",
                "dist_m", "next_stop",
            ])
            for e in clean:
                w.writerow([
                    self.vehicle_name, self.vehicle_type,
                    e.notch, notch_label(e.notch),
                    f"{e.t_start:.2f}",
                    f"{e.t_end - e.t_start:.1f}",
                    f"{e.v_start:.2f}", f"{e.v_end:.2f}",
                    f"{e.v_end - e.v_start:.2f}",
                    f"{e.accel_dv:.4f}",
                    f"{e.accel_api:.4f}" if e.accel_api is not None else "",
                    f"{e.grad_avg:.2f}",
                    grad_band_label(e.grad_avg),
                    f"{e.dist_m:.1f}",
                    e.next_stop or "",
                ])

        # ── CSV: paradas visitadas ────────────────────────────────────────────
        with open(csv_stops_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "station_name", "odo_m", "platform_length_m",
                "dwell_s", "braking_dist_m", "approach_v_mph",
                "approach_grad_pct", "service",
            ])
            for s in self.stops:
                w.writerow([
                    s.station_name,
                    f"{s.odo_m:.0f}",
                    f"{s.platform_length_m:.0f}" if s.platform_length_m else "",
                    f"{s.dwell_s:.1f}",
                    f"{s.braking_dist_m:.0f}",
                    f"{s.approach_v_mph:.1f}",
                    f"{s.approach_grad_pct:.2f}",
                    s.service or "",
                ])

        # ── CSV: cambios de límite de velocidad ───────────────────────────────
        with open(csv_limits_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["odo_m", "limit_mph"])
            for odo, lim in self._limit_log:
                w.writerow([f"{odo:.0f}", f"{lim:.0f}"])

        # ── Agrupar por (notch, banda de gradiente) ───────────────────────────
        groups: dict[tuple[int, str], list[float]] = {}
        for e in clean:
            key = (e.notch, grad_band_label(e.grad_avg))
            val = e.accel_api if e.accel_api is not None else e.accel_dv
            groups.setdefault(key, []).append(val)

        # ── Construir informe ────────────────────────────────────────────────
        lines = [
            "=" * 62,
            "  SESIÓN DE CALIBRACIÓN",
            "=" * 62,
            f"  Vehículo   : {self.vehicle_name}  ({self.vehicle_type})",
            f"  Fecha      : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"  Eventos OK : {len(clean)}  (de {len(self.events)} totales)",
            f"  Paradas    : {len(self.stops)}",
            f"  Odo. total : {self._odo_m / 1000:.2f} km",
            "",
        ]

        def _group_line(notch: int, gband: str, vals: list[float]) -> str:
            mean   = statistics.mean(vals)
            sigma  = statistics.stdev(vals) if len(vals) > 1 else 0.0
            used   = [x for x in vals if abs(x - mean) <= 2 * sigma]
            mean_c = statistics.mean(used) if used else mean
            outlier_note = (f"  ⚠ {len(vals)-len(used)} outlier(s) excluidos"
                            if len(used) < len(vals) else "")
            return (
                f"  {notch_label(notch):20s}  {gband:>7s}  "
                f"a={mean_c:+.3f} m/s²  σ={sigma:.3f}  n={len(vals)}"
                f"{outlier_note}"
            )

        # Frenados (notch 0-3)
        brake_keys = sorted(k for k in groups if k[0] <= 3)
        if brake_keys:
            lines.append("── FRENADOS ──────────────────────────────────────────────")
            for key in brake_keys:
                lines.append(_group_line(key[0], key[1], groups[key]))
            lines.append("")

        # Inercia (notch 4 = neutro)
        coast_keys = sorted(k for k in groups if k[0] == 4)
        if coast_keys:
            lines.append("── INERCIA (neutro) ──────────────────────────────────────")
            for key in coast_keys:
                lines.append(_group_line(key[0], key[1], groups[key]))
            lines.append("")

        # Tracciones (notch 5-8)
        power_keys = sorted(k for k in groups if k[0] >= 5)
        if power_keys:
            lines.append("── TRACCIONES ────────────────────────────────────────────")
            for key in power_keys:
                lines.append(_group_line(key[0], key[1], groups[key]))
            lines.append("")

        # ── Constantes recomendadas (datos en plano ±0.5%) ───────────────────
        lines.append("── CONSTANTES RECOMENDADAS (plano ±0.5%) ─────────────────")

        def _flat_mean(notches: list[int]) -> Optional[float]:
            vals = []
            for n in notches:
                vals += groups.get((n, "+0.0%"), [])
            if not vals:
                return None
            mean  = statistics.mean(vals)
            sigma = statistics.stdev(vals) if len(vals) > 1 else 0.0
            clean_vals = [x for x in vals if abs(x - mean) <= 2 * sigma]
            return statistics.mean(clean_vals) if clean_vals else mean

        recs: dict[str, Optional[float]] = {
            "MAX_DECEL_MS2":    _flat_mean([0]),
            "TARGET_DECEL_MS2": _flat_mean([1, 2, 3]),
            "TARGET_ACCEL_MS2": _flat_mean([7, 8]),
            "COAST_DECEL_MS2":  _flat_mean([4]),
        }

        for const, val in recs.items():
            cur = CURRENT_CONSTANTS[const]
            if val is not None:
                val_abs = abs(val)
                delta   = val_abs - cur
                flag    = " ✓ sin cambio significativo" if abs(delta) < 0.05 else f" ← Δ={delta:+.3f}"
                lines.append(f"  {const:22s} = {val_abs:.3f}  (actual {cur:.2f}){flag}")
            else:
                lines.append(f"  {const:22s} = ?  (sin datos en plano ±0.5%)")

        # ── Paradas visitadas ─────────────────────────────────────────────────
        if self.stops:
            lines.append("")
            lines.append("── PARADAS VISITADAS ─────────────────────────────────────")
            for i, s in enumerate(self.stops, 1):
                plat_str = f"  andén={s.platform_length_m:.0f}m" if s.platform_length_m else ""
                lines.append(
                    f"  {i:2d}. {s.station_name:<30s}"
                    f"  odo={s.odo_m/1000:.2f}km{plat_str}"
                    f"  dwell={s.dwell_s:.0f}s"
                )
                if s.braking_dist_m > 0:
                    lines.append(
                        f"       Frenado: dist={s.braking_dist_m:.0f}m"
                        f"  v_ini={s.approach_v_mph:.1f}mph"
                        f"  grad={s.approach_grad_pct:+.1f}%"
                    )

        # ── Límites de velocidad detectados ──────────────────────────────────
        if self._limit_log:
            lines.append("")
            lines.append("── LÍMITES DE VELOCIDAD ──────────────────────────────────")
            for i, (odo, lim) in enumerate(self._limit_log):
                next_odo = (self._limit_log[i + 1][0] if i + 1 < len(self._limit_log)
                            else self._odo_m)
                lines.append(
                    f"  odo={odo/1000:6.2f}km … {next_odo/1000:.2f}km  →  {lim:.0f} mph"
                )

        lines += [
            "",
            f"  Eventos  : {csv_events_path}",
            f"  Paradas  : {csv_stops_path}",
            f"  Límites  : {csv_limits_path}",
            f"  Resumen  : {txt_path}",
            "=" * 62,
        ]

        report = "\n".join(lines)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(report)

        print("\n" + report)


# ── Entrada principal ─────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profiler pasivo de calibración — TSW6 autopilot",
    )
    parser.add_argument("--host",    default="127.0.0.1",
                        help="IP del RailBridge Companion (default: 127.0.0.1)")
    parser.add_argument("--port",    type=int, default=COMP_PORT)
    parser.add_argument("--vehicle", default=None,
                        help="Nombre del vehículo (override de la detección automática)")
    parser.add_argument("--output",  default="logs",
                        help="Carpeta de salida para CSV y resumen (default: logs/)")
    args = parser.parse_args()

    # Verificar conexión
    base_url = find_companion(args.host, args.port)
    if base_url is None:
        print(f"ERROR: No se puede conectar a {args.host}:{args.port}")
        print("       ¿Está el RailBridge Companion activo y TSW6 ejecutándose?")
        sys.exit(1)
    print(f"Conectado a {base_url}")

    # Detectar nombre del vehículo
    vehicle_name = args.vehicle
    if vehicle_name is None:
        vehicle_name = get_vehicle_name(base_url)
        if vehicle_name:
            print(f"Vehículo detectado: {vehicle_name}")
        else:
            # Intentar leer del primer snapshot SSE
            print("No se pudo leer /vehicles — esperando primer snapshot SSE...")
            for ev_type, data in sse_stream(base_url):
                if ev_type != "dmi_snapshot":
                    continue
                train_id = (data.get("identity", {})
                                .get("train_identifier", {})
                                .get("value"))
                if train_id and str(train_id).strip().lower() not in ("none", ""):
                    vehicle_name = str(train_id).strip()
                    print(f"Vehículo desde SSE: {vehicle_name}")
                    break
                if parse_snapshot(data) is not None:
                    # Snapshot válido pero sin nombre
                    vehicle_name = "Unknown"
                    print("Nombre de vehículo desconocido — usa --vehicle para especificarlo")
                    break

    vehicle_name = vehicle_name or "Unknown"
    profiler = Profiler(vehicle_name=vehicle_name, output_dir=args.output)

    print("  Ctrl+C para finalizar y guardar el informe.\n")

    # Bucle principal: siempre guarda al salir (Ctrl+C, excepción, cierre de ventana)
    try:
        _station_cache: list[dict] = []   # paradas con nombre del dashboard_snapshot

        for ev_type, data in sse_stream(base_url):
            if ev_type == "dashboard_snapshot":
                profiler.feed_doors(parse_doors(data))
                stations = parse_route_stations(data)
                if stations:
                    _station_cache = stations
                continue

            # dmi_snapshot
            sample = parse_snapshot(data)
            if sample is None:
                continue

            # Enriquecer nombre de parada con el caché del dashboard si el dmi no lo trajo
            if _station_cache and sample.next_stop_dist is not None:
                if not sample.next_stop or sample.next_stop == "?":
                    _dist = sample.next_stop_dist
                    best = min(_station_cache,
                               key=lambda s: abs(s["distance_m"] - _dist))
                    if abs(best["distance_m"] - _dist) < 300:
                        sample.next_stop = best["name"]
                        if sample.next_stop_plat_m is None:
                            sample.next_stop_plat_m = best.get("platform_length_m")

            # Detectar emergencia ATP y pasar estado a feed()
            messages = data.get("messages", []) or []
            ack = any(isinstance(m, dict) and m.get("ack_required") for m in messages)

            profiler.feed(sample, corrupt=ack)

    except KeyboardInterrupt:
        pass
    finally:
        profiler.summarize()


if __name__ == "__main__":
    main()
