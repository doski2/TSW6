"""Pestillo rodar↔frenar de la parada de andén MC: evita el ping-pong clic/neutro.

Soltar a neutro (rodar) en la aproximación final permite parar en el tablón en vez de
quedarse 40-58 m corto (181008Z: el clic frena ~0,34 m/s², y desde 13 mph a 100 m solo hacen
falta ~0,17). Para que no conmute en cada tick se exige ``MC_ROLL_SWITCH_MIN_S`` entre cambios.
Lo comparten ``decision`` y el ``grade_hold`` del bucle: ``resolve`` es idempotente en un tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Simulación (clic 0,34 / rodar 0,10 m/s², retardo 0,5 s): 3 s dejan 4-8 conmutaciones por
# parada y paran a ~6 m corto; con ±15 % de error en el clic, a 3-7 m (siempre corto).
MC_ROLL_SWITCH_MIN_S = 3.0


@dataclass
class StationRollLatch:
    active: Optional[bool] = None  # True = rodando en neutro
    since: float = 0.0

    def reset(self) -> None:
        self.active = None
        self.since = 0.0

    def force(self, roll: bool, now: float) -> None:
        """Fija el estado sin esperar el tiempo mínimo (necesidad dura: frenar ya)."""
        if self.active != roll:
            self.active, self.since = roll, now

    def resolve(self, want_roll: bool, now: float) -> bool:
        if self.active is None:
            self.active, self.since = want_roll, now
        elif want_roll != self.active and now - self.since >= MC_ROLL_SWITCH_MIN_S:
            self.active, self.since = want_roll, now
        return self.active
