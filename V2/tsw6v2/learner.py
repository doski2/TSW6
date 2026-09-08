"""Perfil aprendido (opcional) — decel por muesca + L4 lite (fill aire)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Optional

from tsw6v2.brake_air import BrakeAirTracker
from tsw6v2.learner_v1 import V1LearnerData


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
        self._air.observe(lever, brake_cyl_bar, now=now)

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
        return cls(by_notch, air=air, v1=v1, v1_snapshot=snapshot)

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
        if self._v1_snapshot is not None:
            data = copy.deepcopy(self._v1_snapshot)
            data.update(self._air.to_dict())
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._v1_snapshot = data
            return
        data: dict[str, Any] = {
            "decel_by_notch": {str(k): v for k, v in self._by_notch.items()},
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
    def resolve_profile_path(
        cls,
        vehicle: str,
        profiles_dir: Path | None = None,
    ) -> Optional[Path]:
        """``logs/profiles/<vehículo>.json`` si existe."""
        root = profiles_dir or Path("logs/profiles")
        slug = (vehicle or "?").strip().lower().replace(" ", "_")
        path = root / f"{slug}.json"
        return path if path.is_file() else None

    @classmethod
    def load_default(cls, vehicle: str, profiles_dir: Path | None = None) -> LearnerProfile:
        """``logs/profiles/<vehicle>.json`` si existe."""
        path = cls.resolve_profile_path(vehicle, profiles_dir=profiles_dir)
        if path is None:
            return cls()
        return cls.from_json(path)
