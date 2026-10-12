"""Perfil aprendido (opcional) — decel por muesca + L4 lite (fill aire)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Optional

import time

from tsw6v2.brake_air import BrakeAirTracker, brake_decel_sample_ready
from tsw6v2.brake_air_profile import BrakeAirProfile
from tsw6v2.learn_quality import DecelObserveWindow, LearnEvent, decel_outlier_rejected
from tsw6v2.learner_v1 import EMA_ALPHA, MIN_SAMPLES, V1LearnerData, speed_band_index

# Retención en el amperímetro (OBSERVATION de laboratorio: amps negativos).
REGEN_AMPS_BELOW_A = -1.0


class LearnerProfile:
    """Lookup decel por muesca; vacío = usar fracciones fijas del plan."""

    def __init__(
        self,
        by_notch: dict[int, float] | None = None,
        *,
        air: BrakeAirTracker | None = None,
        v1: V1LearnerData | None = None,
        v1_snapshot: dict[str, Any] | None = None,
    ) -> None:
        self._by_notch = dict(by_notch or {})
        self._air = air or BrakeAirTracker()
        self._v1 = v1
        self._v1_snapshot = v1_snapshot
        self._decel_observe_n = 0
        self._regen_n = 0
        self._last_amps: Optional[float] = None
        self._mc_decel_n = 0
        self._by_mc: dict[int, float] = {}
        self._decel_window = DecelObserveWindow()
        self._mc_window = DecelObserveWindow()
        self._learn_event: LearnEvent | None = None

    @property
    def decel_observe_n(self) -> int:
        return self._decel_observe_n

    @property
    def regen_n(self) -> int:
        return self._regen_n

    @property
    def mc_decel_n(self) -> int:
        return self._mc_decel_n

    def mc_decel_for(self, fraction: Optional[float]) -> Optional[float]:
        """Decel aprendida (m/s²) para una posición MC; ``None`` si no hay dato."""
        if fraction is None:
            return None
        return self._by_mc.get(int(round(float(fraction) * 100)))

    def note_amps(self, amps: Optional[float]) -> None:
        """Última lectura de amperios. Retención: ``amps`` < −1 A."""
        self._last_amps = None if amps is None else float(amps)
        if self._electric_brake_now():
            self._regen_n += 1

    def _electric_brake_now(self) -> bool:
        return (
            self._last_amps is not None
            and self._last_amps < REGEN_AMPS_BELOW_A
        )

    def pop_learn_event(self) -> LearnEvent | None:
        ev = self._learn_event
        self._learn_event = None
        return ev

    def _set_learn_event(self, kind: str, accepted: bool, reason: str) -> None:
        self._learn_event = LearnEvent(kind, accepted, reason)

    def _ensure_v1(self) -> V1LearnerData:
        if self._v1 is None:
            self._v1 = V1LearnerData()
            if self._v1_snapshot is None:
                self._v1_snapshot = {}
        return self._v1

    def observe_brake_decel(
        self,
        *,
        handle: int,
        speed_mph: float,
        gradient_pct: float,
        accel_ms2: Optional[float],
        lever: int | None = None,
        brake_cyl_bar: float | None = None,
        now: float | None = None,
    ) -> bool:
        """Registra ``accel_ms2`` tras ventana estable + filtros de calidad.

        Con retención en amperios la muestra no entra en la media de aire.
        """
        if accel_ms2 is None:
            return False
        if self._electric_brake_now():
            self._set_learn_event("decel", False, "electric")
            return False
        if not brake_decel_sample_ready(
            handle=handle,
            lever=lever,
            brake_cyl_bar=brake_cyl_bar,
        ):
            self._set_learn_event("decel", False, "pressure")
            return False

        t = time.monotonic() if now is None else now
        ready = self._decel_window.feed(
            t=t,
            handle=handle,
            speed_mph=speed_mph,
            grad_pct=gradient_pct,
            accel_ms2=float(accel_ms2),
        )
        if ready is None:
            reason = self._decel_window.last_reason
            if not reason.startswith(("accumulating", "stable ")):
                self._set_learn_event("decel", False, reason)
            return False

        handle_i, measured_norm, avg_speed, _avg_grad = ready
        v1 = self._ensure_v1()
        band = speed_band_index(avg_speed)
        band_n = v1.n_bands[band].get(handle_i, 0)
        prior = v1.ema_bands[band].get(handle_i)
        if band_n >= MIN_SAMPLES and decel_outlier_rejected(measured_norm, prior):
            self._set_learn_event("decel", False, "decel_outlier")
            return False
        ok, reason = v1.commit_brake_decel_sample(
            handle=handle_i,
            speed_mph=avg_speed,
            measured_norm=measured_norm,
        )
        self._set_learn_event("decel", ok, reason)
        if not ok:
            return False
        self._decel_observe_n += 1
        return True

    def observe_mc_brake(
        self,
        *,
        fraction: float,
        speed_mph: float,
        gradient_pct: float,
        accel_ms2: Optional[float],
        now: float | None = None,
    ) -> bool:
        """Decel en la posición del combinado. No usa muesca UK ni cilindro 323."""
        if accel_ms2 is None:
            return False
        key = int(round(float(fraction) * 100.0))
        t = time.monotonic() if now is None else now
        ready = self._mc_window.feed(
            t=t,
            handle=key,
            speed_mph=speed_mph,
            grad_pct=gradient_pct,
            accel_ms2=float(accel_ms2),
        )
        if ready is None:
            reason = self._mc_window.last_reason
            if not reason.startswith(("accumulating", "stable ")):
                self._set_learn_event("mc", False, reason)
            return False
        _handle, measured_norm, _avg_speed, _avg_grad = ready
        measured = abs(float(measured_norm))
        prior = self._by_mc.get(key)
        if prior is None:
            self._by_mc[key] = measured
        else:
            self._by_mc[key] = EMA_ALPHA * measured + (1.0 - EMA_ALPHA) * prior
        self._mc_decel_n += 1
        self._set_learn_event("mc", True, "mc")
        return True

    @property
    def brake_fill_s(self) -> float:
        return self._air.brake_fill_s

    @property
    def brake_fill_n(self) -> int:
        return self._air.brake_fill_n

    def observe_air(
        self,
        lever: int,
        brake_cyl_bar: float | None,
        *,
        now: float | None = None,
    ) -> None:
        ev = self._air.observe(lever, brake_cyl_bar, now=now)
        if ev is not None:
            self._set_learn_event(ev.kind, ev.accepted, ev.reason)

    def apply_vehicle_brake_profile(
        self,
        package: dict[str, Any] | None,
    ) -> BrakeAirProfile:
        profile = BrakeAirProfile.from_vehicle_package(package)
        self._air.set_profile(profile)
        return profile

    def air_ready(
        self,
        brake_cyl_bar: float | None,
        *,
        lever: int | None = None,
    ) -> bool:
        return self._air.air_ready(brake_cyl_bar, lever=lever)

    def inhibit_reapply(
        self,
        brake_cyl_bar: float | None,
        *,
        now: float | None = None,
    ) -> bool:
        return self._air.inhibit_reapply(brake_cyl_bar, now=now)

    def cap_escalation(
        self,
        *,
        committed: int | None,
        requested: int,
        brake_cyl_bar: float | None,
    ) -> int:
        return self._air.cap_escalation(
            committed=committed,
            requested=requested,
            brake_cyl_bar=brake_cyl_bar,
        )

    def predict_decel(
        self,
        handle_notch: int,
        speed_mph: float,
        gradient_pct: float,
    ) -> Optional[float]:
        handle = int(handle_notch)
        flat = self._by_notch.get(handle)
        if flat is not None and flat > 0.05:
            return float(flat)
        if self._v1 is not None:
            return self._v1.predict_brake_decel_ms2(handle, speed_mph, gradient_pct)
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearnerProfile:
        raw = data.get("decel_by_notch") or data.get("notch_decel") or {}
        by_notch = {int(k): float(v) for k, v in raw.items()}
        air = BrakeAirTracker()
        air.load_dict(data)
        v1 = V1LearnerData.from_dict(data)
        snapshot = copy.deepcopy(data) if v1 is not None else None
        profile = cls(by_notch, air=air, v1=v1, v1_snapshot=snapshot)
        mc_raw = data.get("decel_by_mc") or {}
        profile._by_mc = {int(k): float(v) for k, v in mc_raw.items()}
        return profile

    @classmethod
    def from_json(cls, path: Path) -> LearnerProfile:
        if not path.is_file():
            return cls()
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls.from_dict(data)

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._v1 is not None:
            data = copy.deepcopy(self._v1_snapshot) if self._v1_snapshot else {}
            data.update(self._v1.to_dict())
            if self._by_notch:
                data["decel_by_notch"] = {str(k): v for k, v in self._by_notch.items()}
            if self._by_mc:
                data["decel_by_mc"] = {str(k): v for k, v in self._by_mc.items()}
            data.update(self._air.to_dict())
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._v1_snapshot = data
            return
        data: dict[str, Any] = {
            "decel_by_notch": {str(k): v for k, v in self._by_notch.items()},
            "decel_by_mc": {str(k): v for k, v in self._by_mc.items()},
            **self._air.to_dict(),
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @property
    def has_decel_profile(self) -> bool:
        if self._by_notch:
            return True
        if self._v1 is None:
            return False
        for handle in (1, 2, 3):
            if self._v1.predict_brake_decel_ms2(handle, 50.0, 0.0) is not None:
                return True
        return False

    @classmethod
    def profile_path_for_vehicle(
        cls,
        vehicle: str,
        profiles_dir: Path | None = None,
    ) -> Optional[Path]:
        """Ruta estándar ``logs/profiles/<vehículo>.json`` (crear al guardar)."""
        if not vehicle or vehicle == "?":
            return None
        root = profiles_dir or Path("logs/profiles")
        slug = vehicle.strip().lower().replace(" ", "_")
        return root / f"{slug}.json"

    @classmethod
    def resolve_profile_path(
        cls,
        vehicle: str,
        profiles_dir: Path | None = None,
    ) -> Optional[Path]:
        """``logs/profiles/<vehículo>.json`` si existe."""
        path = cls.profile_path_for_vehicle(vehicle, profiles_dir=profiles_dir)
        return path if path is not None and path.is_file() else None

    @classmethod
    def load_default(cls, vehicle: str, profiles_dir: Path | None = None) -> LearnerProfile:
        """``logs/profiles/<vehicle>.json`` si existe."""
        path = cls.resolve_profile_path(vehicle, profiles_dir=profiles_dir)
        if path is None:
            return cls()
        return cls.from_json(path)
