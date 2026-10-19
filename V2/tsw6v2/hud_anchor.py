"""Ancla la distancia de parada al HUD del juego (OCR).

``TrackData`` da el fin del andén; el HUD marca el punto de parada (el tablón), que está
entre ~35 y ~120 m antes (Fleetwood 94,9 / 95,7 / 101,0 m en 3 sesiones, desviación ~5 m).
El objetivo es parar donde marca el HUD, así que la lectura OCR manda y HTTP queda de
referencia (``docs/v2/HUD_OCR_MEDICION.md``).

Cómo se mantiene la seguridad (el OCR es ruidoso y solo se ve con el marcador en pantalla):

1. **Cambio de marco** (fin de andén → tablón): hacen falta dos capturas seguidas con el mismo
   desfase (±``CONFIRM_AGREE_M``) y dentro de ``[FRAME_MIN_M, FRAME_MAX_M]``. Una lectura rota
   (p. ej. «0 m» con el tablón a 1,5 km) no entra.
2. **Seguimiento**: una captura que difiere de la estimación más de ``TRACK_GATE_M`` se
   descarta, y la corrección por captura se limita a ``MAX_CORRECTION_M``. Un fallo de OCR que
   cuele no puede mover la distancia más que eso.
3. **HTTP** sigue entrando: ya en marco tablón se le resta el desfase aprendido.
4. Sin lectura (marcador fuera de pantalla, OCR caído) la distancia sigue por v×dt como antes.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from tsw6v2.constants import MPH_TO_MS

# fin de andén − tablón (m): el tablón está antes que el fin del andén
FRAME_MIN_M = -15.0
FRAME_MAX_M = 250.0
CONFIRM_AGREE_M = 12.0
TRACK_GATE_M = 40.0
MAX_CORRECTION_M = 15.0
RESYNC_AFTER_GATED = 3  # capturas seguidas coherentes entre sí que contradicen la estimación
MIN_SPEED_MPH = 3.0
MIN_HUD_M = 3.0  # por debajo se está sobre el marcador: la lectura ya no aporta
OFFSET_EMA = 0.3
HTTP_REFINE_MAX_AGE_S = 3.0


@dataclass
class AnchorReading:
    """Lectura del HUD: ``value_m`` en el instante ``t`` (``time.monotonic()``)."""

    value_m: float
    t: float


# ¿La distancia de estación va ya en el marco del tablón? La fija el bucle cada tick; la leen las
# reglas de andén que interpretan «stn≈0» (``p1_station_gate``).
_BOARD_FRAME: ContextVar[bool] = ContextVar("tsw6_board_frame", default=False)


def set_board_frame(active: bool) -> None:
    _BOARD_FRAME.set(bool(active))


def board_frame_active() -> bool:
    return _BOARD_FRAME.get()


def hud_ocr_control_enabled() -> bool:
    """``TSW6_HUD_OCR_CONTROL=1``: el HUD (OCR) manda sobre la distancia de parada."""
    return os.environ.get("TSW6_HUD_OCR_CONTROL", "").strip().lower() in ("1", "true", "yes", "on")


class HudAnchor:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.board_frame = False
        self.offset_m: Optional[float] = None  # fin de andén − tablón
        self.accepted_n = 0
        self.rejected_n = 0
        self.last_reason = ""
        self.last_corr_m = 0.0
        self._last_t: Optional[float] = None
        self._cand_diff: Optional[float] = None
        self._last_accept_t: Optional[float] = None
        self._gate_diff: Optional[float] = None
        self._gate_streak = 0

    def apply(
        self,
        est_m: Optional[float],
        reading: Optional[AnchorReading],
        *,
        now: float,
        speed_mph: float,
    ) -> Optional[float]:
        """Distancia corregida (en el marco actual) o ``None`` si no hay que cambiarla."""
        if reading is None or est_m is None:
            return None
        if self._last_t is not None and reading.t == self._last_t:
            return None  # captura ya procesada
        self._last_t = reading.t
        if speed_mph < MIN_SPEED_MPH:
            return self._reject("slow")
        hud_now = reading.value_m - speed_mph * MPH_TO_MS * max(0.0, now - reading.t)
        if hud_now < MIN_HUD_M:
            return self._reject("on_marker")

        if not self.board_frame:
            diff = est_m - hud_now
            if not FRAME_MIN_M <= diff <= FRAME_MAX_M:
                self._cand_diff = None
                return self._reject("frame_gate")
            if self._cand_diff is None or abs(diff - self._cand_diff) > CONFIRM_AGREE_M:
                self._cand_diff = diff
                self.last_reason = "confirming"
                return None
            self.board_frame = True
            self.offset_m = 0.5 * (diff + self._cand_diff)
            self.last_corr_m = hud_now - est_m
            self._accept(now)
            return hud_now

        diff = hud_now - est_m
        if abs(diff) > TRACK_GATE_M:
            return self._gated(diff, hud_now, now)
        self._gate_streak = 0
        corr = max(-MAX_CORRECTION_M, min(MAX_CORRECTION_M, diff))
        self.last_corr_m = corr
        self._accept(now)
        return est_m + corr

    def note_http_end(self, http_end_m: float, est_m: Optional[float], *, now: float) -> None:
        """Afina el desfase fin de andén − tablón con una lectura HTTP, si el ancla es reciente."""
        if (
            not self.board_frame
            or est_m is None
            or self._last_accept_t is None
            or now - self._last_accept_t > HTTP_REFINE_MAX_AGE_S
        ):
            return
        sample = http_end_m - est_m
        if not FRAME_MIN_M <= sample <= FRAME_MAX_M:
            return
        base = sample if self.offset_m is None else self.offset_m
        self.offset_m = (1.0 - OFFSET_EMA) * base + OFFSET_EMA * sample

    def to_board(self, http_end_m: float) -> float:
        """Lectura HTTP (fin de andén) en el marco del tablón, si ya se aprendió el desfase."""
        if self.board_frame and self.offset_m is not None:
            return max(0.0, http_end_m - self.offset_m)
        return http_end_m

    def status(self) -> str:
        if not self.board_frame:
            return f"wait {self.last_reason}".strip()
        return (
            f"board off={self.offset_m or 0.0:.0f} n={self.accepted_n} "
            f"c={self.last_corr_m:+.1f} {self.last_reason}"
        ).strip()

    def _gated(self, diff: float, hud_now: float, now: float) -> Optional[float]:
        """Captura fuera de puerta. Si varias seguidas coinciden entre sí, la estimación es la errónea."""
        if self._gate_diff is not None and abs(diff - self._gate_diff) <= CONFIRM_AGREE_M:
            self._gate_streak += 1
        else:
            self._gate_streak = 1
        self._gate_diff = diff
        if self._gate_streak < RESYNC_AFTER_GATED:
            return self._reject("track_gate")
        self._gate_streak = 0
        self.last_corr_m = diff
        self._accept(now)
        self.last_reason = "resync"
        return hud_now

    def _accept(self, now: float) -> None:
        self.accepted_n += 1
        self.last_reason = ""
        self._last_accept_t = now

    def _reject(self, reason: str) -> Optional[float]:
        self.rejected_n += 1
        self.last_reason = reason
        return None
