"""``service_brake``: plan de parada → objetivo y mando (andén / señal)."""

from __future__ import annotations

from typing import Optional

from tsw6v2.plan import BrakePlan, BrakePlanStep
from tsw6v2.service_brake import (
    command_from_stop_target,
    should_release_over_braked_for_stop_target,
    target_from_stop_plan,
)
from tsw6v2.target import BrakeTargetResult


def _step(*, dist_start: float, apply_now: bool, handle: int = 3, decel: float = 0.5) -> BrakePlanStep:
    return BrakePlanStep(
        notch="B1",
        handle_notch=handle,
        phase="B1",
        distance_m=300.0,
        apply_at_remaining_m=300.0 - dist_start,
        dist_start=dist_start,
        meters_until_action_m=max(0.0, dist_start),
        apply_now=apply_now,
        decel_ms2=decel,
    )


def _plan(step: Optional[BrakePlanStep], *, dist: float = 300.0) -> BrakePlan:
    return BrakePlan(
        target_kind="STATION",
        distance_to_target_m=dist,
        target_speed_mph=0.0,
        reaction_margin_m=10.0,
        steps=[step] if step is not None else [],
        active_step=step,
    )


def _target(*, handle: int = 3, apply_now: bool = True) -> BrakeTargetResult:
    # La ventana de APPLY la fija la cinemática (``dist_start``), no ``apply_now`` solo:
    # sin aplicar = aún lejos de la ventana.
    return BrakeTargetResult(
        target_kind="STATION",
        distance_m=200.0 if apply_now else 1500.0,
        target_speed_mph=0.0,
        handle_notch=handle,
        phase="B1",
        dist_start=0.0 if apply_now else 1000.0,
        apply_now=apply_now,
        detail="t",
    )


def test_sin_paso_activo_no_hay_objetivo() -> None:
    assert target_from_stop_plan(_plan(None), speed_mph=30.0, detail="x") is None


def test_paso_en_ventana_da_apply_now_con_decel_del_plan() -> None:
    tgt = target_from_stop_plan(
        _plan(_step(dist_start=0.0, apply_now=True, decel=0.42)), speed_mph=30.0, detail="x"
    )
    assert tgt is not None
    assert tgt.apply_now is True
    assert tgt.plan_decel_ms2 == 0.42
    assert tgt.handle_notch == 3


def test_lejos_de_la_ventana_solo_vigila_si_se_permite() -> None:
    plan = _plan(_step(dist_start=500.0, apply_now=False), dist=900.0)
    assert target_from_stop_plan(plan, speed_mph=30.0, detail="x") is None
    watch = target_from_stop_plan(plan, speed_mph=30.0, detail="x", allow_watch=True)
    assert watch is not None
    assert watch.apply_now is False


def test_max_apply_distance_aplaza_el_apply() -> None:
    plan = _plan(_step(dist_start=0.0, apply_now=True), dist=800.0)
    assert (
        target_from_stop_plan(plan, speed_mph=30.0, detail="x", max_apply_distance_m=400.0)
        is None
    )
    watch = target_from_stop_plan(
        plan, speed_mph=30.0, detail="x", allow_watch=True, max_apply_distance_m=400.0
    )
    assert watch is not None and watch.apply_now is False


def test_soltar_solo_si_la_palanca_hereda_mas_freno_que_el_plan() -> None:
    t = _target(handle=3)  # plan: B1
    assert should_release_over_braked_for_stop_target(t, 1) is True  # B3 > B1
    assert should_release_over_braked_for_stop_target(t, 2) is True  # B2 > B1
    assert should_release_over_braked_for_stop_target(t, 3) is False  # igual
    assert should_release_over_braked_for_stop_target(t, 4) is False  # neutro: sin freno


def test_comando_apply_desde_objetivo_activo() -> None:
    cmd = command_from_stop_target(
        _target(handle=3, apply_now=True), current_notch=4, speed_mph=30.0
    )
    assert cmd is not None
    assert cmd.kind == "APPLY"


def test_comando_release_si_hereda_sobrefreno_y_el_plan_no_aplica() -> None:
    cmd = command_from_stop_target(
        _target(handle=3, apply_now=False), current_notch=1, speed_mph=30.0
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"


def test_sin_mando_en_neutro_y_plan_sin_aplicar() -> None:
    assert (
        command_from_stop_target(
            _target(handle=3, apply_now=False), current_notch=4, speed_mph=30.0
        )
        is None
    )
