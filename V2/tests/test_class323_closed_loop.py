"""Class 323 en lazo cerrado (simulador de ``closed_loop_sim``): parada y parpadeo de muesca.

El modelo es una aproximación calibrada con las ventanas de freno estable de las sesiones
20261023 (decel en llano B1 0,60 / B2 0,85 / B3 1,1 m/s²). Sirve para comparar variantes de la
lógica en igualdad de condiciones, no para sustituir una prueba en el juego.
"""

from __future__ import annotations

from typing import Any

import pytest

import tsw6v2.decision_finalize as finalize
from closed_loop_sim import simulate

# (v0 mph, distancia al tablón m, pendiente %): aproximaciones vistas en las sesiones reales.
SCENARIOS = [
    (35.0, 620.0, 0.0),
    (25.0, 300.0, 0.0),
    (50.0, 900.0, 0.0),
    (57.9, 757.0, -1.05),  # Gravelly Hill
    (45.3, 393.0, -1.05),  # parpadeo B1↔B2 a 897 s
]


@pytest.mark.parametrize("v0,dist,grad", SCENARIOS)
def test_para_cerca_del_tablon_sin_pasarse(v0: float, dist: float, grad: float) -> None:
    r = simulate(v0_mph=v0, dist_m=dist, grad_pct=grad, limit_next=(50.0, dist + 2500.0), max_s=150.0)
    assert -5.0 <= r.stop_dist_m <= 60.0, f"paró a {r.stop_dist_m:.1f} m del tablón"


@pytest.mark.parametrize("v0,dist,grad", SCENARIOS)
def test_sin_parpadeo_de_muesca(v0: float, dist: float, grad: float) -> None:
    r = simulate(v0_mph=v0, dist_m=dist, grad_pct=grad, limit_next=(50.0, dist + 2500.0), max_s=150.0)
    assert r.quick_reversals <= 2, f"{r.quick_reversals} inversiones de muesca en < 3 s"


def test_el_tiempo_minimo_antes_de_aflojar_reduce_el_parpadeo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con B2/B3 medidos, sin el tiempo mínimo el plan alterna B1↔B2 (9 inversiones en el simulador)."""
    args: dict[str, Any] = dict(
        v0_mph=45.3, dist_m=393.0, grad_pct=-1.05, limit_next=(50.0, 2893.0), max_s=150.0
    )
    con = simulate(**args)
    monkeypatch.setattr(finalize, "NOTCH_WEAKEN_HOLD_SEQ", 0)
    sin = simulate(**args)
    assert sin.quick_reversals >= 5, "el caso debe reproducir el parpadeo sin el tiempo mínimo"
    assert con.quick_reversals < sin.quick_reversals


# ----------------------------------------------------------------------------- señales (§7.9)
# (v0 mph, posición del semáforo desde el inicio, m): rojo permanente.
RED_SIGNALS = [(25.0, 200.0), (35.0, 400.0), (45.0, 600.0), (50.0, 700.0), (55.0, 900.0), (60.0, 1000.0)]


@pytest.mark.parametrize("v0,pos", RED_SIGNALS)
def test_para_antes_del_semaforo_en_rojo(v0: float, pos: float) -> None:
    """Con horizonte fijo de 150 m el agente cruzaba el rojo a 50 y 55 mph (no hay distancia)."""
    r = simulate(v0_mph=v0, dist_m=99999.0, station=False, signal_pos_m=pos, max_s=120.0)
    assert r.stopped, "no llegó a parar"
    assert not r.passed_red, "cruzó el semáforo en rojo"
    assert r.signal_margin_m is not None and 3.0 <= r.signal_margin_m <= 80.0, (
        f"paró a {r.signal_margin_m:.1f} m del poste"
    )


def test_rojo_antes_del_anden_para_en_el_poste() -> None:
    """Rojo a 150 m antes del andén: la parada es el poste, no el andén."""
    r = simulate(
        v0_mph=45.0,
        dist_m=950.0,
        signal_pos_m=800.0,
        limit_next=(50.0, 3450.0),
        max_s=150.0,
    )
    assert r.stopped and not r.passed_red
    assert r.signal_margin_m is not None and 3.0 <= r.signal_margin_m <= 80.0


def test_horizonte_de_senal_no_cambia_hasta_30_mph_y_crece_por_encima() -> None:
    from tsw6v2.signal_plan import (
        SIGNAL_BRAKE_HORIZON_M,
        SIGNAL_EARLY_BRAKE_HORIZON_M,
        SIGNAL_WATCH_LIMIT_DEFER_M,
        signal_apply_horizon_m,
    )

    decel, fill = 1.071, 2.5
    # ≤ 30 mph: idéntico con o sin la decel (se afinó con sesiones reales: 152037Z, 200405Z…)
    assert signal_apply_horizon_m(15.0, base_decel=decel, brake_fill_s=fill) == SIGNAL_BRAKE_HORIZON_M
    assert signal_apply_horizon_m(25.0, base_decel=decel, brake_fill_s=fill) == SIGNAL_EARLY_BRAKE_HORIZON_M
    assert signal_apply_horizon_m(30.0, base_decel=decel, brake_fill_s=fill) == SIGNAL_EARLY_BRAKE_HORIZON_M
    # > 30 mph sin decel (llamadas antiguas): 150 m fijos
    assert signal_apply_horizon_m(50.0) == SIGNAL_WATCH_LIMIT_DEFER_M
    # > 30 mph con decel: al menos la distancia de parada de servicio
    h50 = signal_apply_horizon_m(50.0, base_decel=decel, brake_fill_s=fill)
    h35 = signal_apply_horizon_m(35.0, base_decel=decel, brake_fill_s=fill)
    assert h50 > 300.0
    assert SIGNAL_WATCH_LIMIT_DEFER_M <= h35 < h50
