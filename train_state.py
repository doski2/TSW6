#!/usr/bin/env python3
"""
train_state.py — Instantánea inmutable del estado del tren.

TrainState centraliza todos los datos de telemetría en un único objeto
frozen (de solo lectura), eliminando los ~20 parámetros sueltos del
diseño anterior y garantizando que todos los módulos de control (decider,
controller, watchdog) trabajan con la misma vista del estado en cada ciclo.

Regla de oro: NADIE escribe en TrainState después de construirlo.
Se construye una vez por ciclo con build_train_state() y fluye de módulo
en módulo sin modificarse.
"""

import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TrainState:
    """
    Instantánea inmutable del estado del tren en un ciclo de control.

    Los campos provienen de:
    - Telemetría directa del juego (speed_mph, limit_mph, handle_notch, …)
    - Cálculos de TrainPhysics (acceleration_ms2)
    - Estado de la FSM de estación (station_state, station_name)
    - Configuración del operador (target_mph, paused)

    Las propiedades derivadas (throttle_notch, brake_active, …) se calculan
    al vuelo para mantener el objeto ligero y sin redundancia de datos.
    """

    # ── Velocidad y límites ───────────────────────────────────────────────
    speed_mph: float                   # velocidad actual del tren
    limit_mph: float                   # límite de vía activo
    target_mph: float                  # velocidad objetivo del operador (0 = seguir límite)

    # ── Handle combinado PowerBrakeHandle (Class 323) ─────────────────────
    # 0 = freno máx … 4 = neutro … 8 = tracción máx
    # REGLA PRINCIPAL: siempre leído de telemetría, nunca de un contador interno
    handle_notch: int

    # ── Física ───────────────────────────────────────────────────────────
    acceleration_ms2: Optional[float]  # m/s², de API o acelerómetro dv/dt
    gradient_pct: float                # pendiente en % (+subida, −bajada)
    rain_intensity: float              # 0.0 = seco, 1.0 = tormenta

    # ── Límites próximos ─────────────────────────────────────────────────
    next_limit_mph: Optional[float]
    distance_next_m: Optional[float]
    brake_marker_m: Optional[float]
    speed_limits_ahead: Optional[tuple]  # tuple (inmutable) para frozen=True

    # ── ATP / supervisión ────────────────────────────────────────────────
    supervision: str                   # "csm" | "tsm" | "overspeed"
    ack_required: bool

    # ── Estación y puertas ───────────────────────────────────────────────
    stations: Optional[tuple]          # tuple (inmutable) para frozen=True
    doors_open: bool
    doors_dmi: Optional[bool]
    ocr_stop_dist_m: Optional[float]
    ocr_task: Optional[str]

    # ── FSM de estación (actualizado cada ciclo por SpeedDecider.decide()) ─
    station_state: Optional[str]       # None | APPROACHING | STOPPED | DEPARTING
    station_name: Optional[str]

    # ── Configuración del operador ────────────────────────────────────────
    paused: bool

    # ── Metadata ─────────────────────────────────────────────────────────
    timestamp: float

    # ── Propiedades derivadas (calculadas, no almacenadas) ────────────────

    @property
    def throttle_notch(self) -> int:
        """Zona de tracción del handle: 0-4 (handle 4→8)."""
        return max(0, self.handle_notch - 4)

    @property
    def brake_notch(self) -> int:
        """Zona de freno del handle: 0-4 (handle 4→0)."""
        return max(0, 4 - self.handle_notch)

    @property
    def throttle_active(self) -> bool:
        """True si el handle está en zona de tracción (handle > 4)."""
        return self.handle_notch > 4

    @property
    def brake_active(self) -> bool:
        """True si el handle está en zona de freno (handle < 4)."""
        return self.handle_notch < 4

    @property
    def effective_target(self) -> float:
        """Velocidad máxima efectiva: min(target, límite). Si target=0, usa límite."""
        if self.target_mph > 0:
            return min(self.target_mph, self.limit_mph)
        return self.limit_mph


def build_train_state(
    telem: dict,
    *,
    target_mph: float = 0.0,
    paused: bool = False,
    acceleration_ms2: Optional[float] = None,
    station_state: Optional[str] = None,
    station_name: Optional[str] = None,
    ocr_stop_dist_m: Optional[float] = None,
    ocr_task: Optional[str] = None,
) -> TrainState:
    """
    Construye TrainState a partir del dict de telemetría crudo del juego.

    Los campos que no provienen del stream SSE (aceleración calculada,
    estado FSM, OCR) se pasan como keyword arguments separados porque
    su origen es distinto.

    Convierte listas a tuples para mantener la inmutabilidad de frozen=True.
    """
    stations_raw   = telem.get("stations")
    speed_lims_raw = telem.get("speed_limits_ahead")

    return TrainState(
        speed_mph          = float(telem.get("speed_mph") or 0.0),
        limit_mph          = float(telem.get("limit_mph") or 0.0),
        target_mph         = target_mph,
        handle_notch       = int(telem.get("handle_notch") or 4),
        acceleration_ms2   = acceleration_ms2,
        gradient_pct       = float(telem.get("gradient_pct") or 0.0),
        rain_intensity     = float(telem.get("rain_intensity") or 0.0),
        next_limit_mph     = telem.get("next_limit_mph"),
        distance_next_m    = telem.get("distance_next_m"),
        brake_marker_m     = telem.get("brake_marker_m"),
        speed_limits_ahead = tuple(speed_lims_raw) if speed_lims_raw else None,
        supervision        = str(telem.get("supervision") or "csm"),
        ack_required       = bool(telem.get("ack_required", False)),
        stations           = tuple(stations_raw) if stations_raw else None,
        doors_open         = bool(telem.get("doors_open", False)),
        doors_dmi          = telem.get("doors_dmi"),
        ocr_stop_dist_m    = ocr_stop_dist_m,
        ocr_task           = ocr_task,
        station_state      = station_state,
        station_name       = station_name,
        paused             = paused,
        timestamp          = time.time(),
    )
