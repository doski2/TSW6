#!/usr/bin/env python3
"""
Telemetría rápida para decisiones de control (V2).

La API HTTP de TSW no es push: cada lectura es una petición. Este módulo:
  1. Intenta suscripción batched (1 GET /subscription por ciclo).
  2. Si falla, hace polling secuencial mínimo (speed + mando + freno + acel).

Para decisiones en tiempo real el objetivo es mod UE4SS (ver docs/ARQUITECTURA.md).
La API TSW directa sirve para diagnóstico y escritura de frenos.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from tsw_api_client import TswApiClient, client_from_key_file

DRIVABLE = "CurrentDrivableActor"
DEFAULT_SUBSCRIPTION_ID = 7

CONTROL_PATHS: tuple[str, ...] = (
    f"{DRIVABLE}.Function.HUD_GetSpeed",
    f"{DRIVABLE}.Function.HUD_GetPowerHandle",
    f"{DRIVABLE}.Function.HUD_GetTrainBrakeHandle",
    f"{DRIVABLE}.Function.HUD_GetAcceleration",
)

FALLBACK_KEYS: dict[str, str] = {
    f"{DRIVABLE}.Function.HUD_GetSpeed": "speed",
    f"{DRIVABLE}.Function.HUD_GetPowerHandle": "power",
    f"{DRIVABLE}.Function.HUD_GetTrainBrakeHandle": "train_brake",
    f"{DRIVABLE}.Function.HUD_GetAcceleration": "accel",
}


@dataclass
class ControlSnapshot:
    """Estado mínimo para frenado / gobernanza de velocidad."""

    speed_ms: Optional[float] = None
    power: Optional[float] = None
    power_negative: bool = False
    train_brake: Optional[float] = None
    accel_ms2: Optional[float] = None
    age_ms: float = 0.0
    source: str = "none"  # subscription | poll | stale

    @property
    def speed_mph(self) -> Optional[float]:
        if self.speed_ms is None:
            return None
        return self.speed_ms * 2.236936


class FastControlReader:
    """
    Lector de baja latencia para el bucle de control.

    Tras ``setup()``, ``read()`` devuelve un ``ControlSnapshot`` reutilizando
    la misma sesión HTTP (las lecturas secuenciales cuestan ~15 ms cada una
    una vez calentada la conexión).
    """

    def __init__(
        self,
        client: TswApiClient,
        subscription_id: int = DEFAULT_SUBSCRIPTION_ID,
        paths: tuple[str, ...] = CONTROL_PATHS,
    ) -> None:
        self.client = client
        self.subscription_id = subscription_id
        self.paths = paths
        self._use_subscription = False
        self._last: ControlSnapshot = ControlSnapshot()
        self._warmed = False

    def setup(self) -> bool:
        """Registra paths en la suscripción TSW. Devuelve True si al menos uno OK."""
        ok_any = False
        for path in self.paths:
            if self.client.subscribe_path(self.subscription_id, path):
                ok_any = True
        self._use_subscription = ok_any
        if ok_any:
            self._probe_subscription()
        return ok_any or self._warm_poll()

    def _probe_subscription(self) -> None:
        entries = self.client.read_subscription(self.subscription_id)
        if entries:
            snap = self._parse_subscription(entries)
            if snap.speed_ms is not None:
                self._last = snap
                self._use_subscription = True
                return
        self._use_subscription = False

    def _warm_poll(self) -> bool:
        snap = self._poll_sequential()
        self._warmed = snap.speed_ms is not None
        if self._warmed:
            self._last = snap
        return self._warmed

    def read(self) -> ControlSnapshot:
        t0 = time.perf_counter()
        if self._use_subscription:
            entries = self.client.read_subscription(self.subscription_id)
            if entries:
                snap = self._parse_subscription(entries)
                if snap.speed_ms is not None:
                    snap.age_ms = (time.perf_counter() - t0) * 1000
                    snap.source = "subscription"
                    self._last = snap
                    return snap
            self._use_subscription = False

        snap = self._poll_sequential()
        snap.age_ms = (time.perf_counter() - t0) * 1000
        snap.source = "poll" if snap.speed_ms is not None else "stale"
        if snap.speed_ms is not None:
            self._last = snap
        else:
            stale = ControlSnapshot(**{**self._last.__dict__})
            stale.age_ms = snap.age_ms
            stale.source = "stale"
            return stale
        return snap

    def _poll_sequential(self) -> ControlSnapshot:
        snap = ControlSnapshot()
        speed = self.client.get_node(CONTROL_PATHS[0])
        if speed:
            snap.speed_ms = speed.get("Speed (ms)")
        power = self.client.get_node(CONTROL_PATHS[1])
        if power:
            snap.power = power.get("Power")
            snap.power_negative = bool(power.get("IsNegative", False))
        brake = self.client.get_node(CONTROL_PATHS[2])
        if brake:
            snap.train_brake = brake.get("HandlePosition")
        accel = self.client.get_node(CONTROL_PATHS[3])
        if accel:
            snap.accel_ms2 = accel.get("Acceleration (ms2)")
        return snap

    def _parse_subscription(self, entries: list[dict[str, Any]]) -> ControlSnapshot:
        snap = ControlSnapshot()
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("NodeValid", True):
                continue
            path = str(entry.get("Path") or "")
            values = entry.get("Values")
            if not isinstance(values, dict):
                continue
            self._apply_values(snap, path, values)
        return snap

    def _apply_values(self, snap: ControlSnapshot, path: str, values: dict[str, Any]) -> None:
        if path.endswith("HUD_GetSpeed") or "Speed (ms)" in values:
            if "Speed (ms)" in values:
                snap.speed_ms = values.get("Speed (ms)")
        elif path.endswith("HUD_GetPowerHandle") or "Power" in values:
            snap.power = values.get("Power")
            snap.power_negative = bool(values.get("IsNegative", False))
        elif path.endswith("HUD_GetTrainBrakeHandle") or "HandlePosition" in values:
            if "HandlePosition" in values:
                snap.train_brake = values.get("HandlePosition")
        elif path.endswith("HUD_GetAcceleration") or "Acceleration (ms2)" in values:
            if "Acceleration (ms2)" in values:
                snap.accel_ms2 = values.get("Acceleration (ms2)")

    def close(self) -> None:
        for path in self.paths:
            self.client.unsubscribe(self.subscription_id, path)


def reader_from_key_file() -> Optional[FastControlReader]:
    client = client_from_key_file()
    if client is None:
        return None
    return FastControlReader(client, subscription_id=DEFAULT_SUBSCRIPTION_ID)


def benchmark(reader: FastControlReader, samples: int = 20) -> dict[str, float | str]:
    """Mide latencia media (ms) y Hz efectivos — útil con juego en marcha."""
    reader.setup()
    times: list[float] = []
    for _ in range(samples):
        t0 = time.perf_counter()
        reader.read()
        times.append(time.perf_counter() - t0)
    avg = sum(times) / len(times) if times else 0.0
    return {
        "avg_ms": avg * 1000,
        "hz": 1.0 / avg if avg > 0 else 0.0,
        "source": reader._last.source,
    }
