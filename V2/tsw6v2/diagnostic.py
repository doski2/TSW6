"""Diagnósticos in-game (test IPC B1)."""

from __future__ import annotations

from typing import Any

from tsw6v2.vehicle_package import (
    combined_notch_to_ipc_value,
    resolve_vehicle_package,
    uses_mc_analog_ipc,
)
from tsw6v2.bridge.getdata import ProbeSnapshot, default_getdata_path
from tsw6v2.bridge.ipc_bus import bridge_dir, purge_lua_commands
from tsw6v2.constants import (
    B1_MIN_CYL_RISE_BAR,
    B1_MIN_TRAIN_BRAKE,
    B1_NOTCH,
    IPC_ACK_TIMEOUT_S,
    MS_TO_MPH,
    NEUTRAL_NOTCH,
    PROBE_STALE_S,
)
from tsw6v2.ipc import drive_to_notch, ipc_steps_needed, probe_lever
from tsw6v2.probe import fmt_num, is_probe_fresh, print_getdata_summary, read_snapshot


def _b1_brake_evidence(
    snap: ProbeSnapshot | None,
    lever: int | None,
    *,
    baseline: ProbeSnapshot | None = None,
) -> bool:
    """Efecto físico/HUD tras B1 (323 train_brake; M3a MC a veces 0 % + sube cilindro)."""
    if snap is None:
        return False
    if snap.train_brake is not None and float(snap.train_brake) >= B1_MIN_TRAIN_BRAKE:
        return True
    if (
        baseline is not None
        and snap.brake_cyl_bar is not None
        and baseline.brake_cyl_bar is not None
        and float(snap.brake_cyl_bar) - float(baseline.brake_cyl_bar)
        >= B1_MIN_CYL_RISE_BAR
    ):
        return True
    if lever is None or int(lever) != B1_NOTCH or snap.power is None:
        return False
    p = float(snap.power)
    if snap.power_neg:
        p = -abs(p)
    # OBSERVATION M3a MNR 20261003: a veces train_brake HUD 0 con power ~ -0.8
    return p <= -0.7


def _vehicle_package(snap: ProbeSnapshot | None) -> dict[str, Any] | None:
    if snap is None:
        return None
    return resolve_vehicle_package(snap.vehicle)


def _mc_vehicle_name_heuristic(snap: ProbeSnapshot) -> bool:
    """Sin paquete G-B: aviso por nombre GetData (M3a/M7a)."""
    v = str(snap.vehicle or "").upper()
    return "M3A" in v or "M7A" in v


def _mc_b1_ipc_pass(
    snap0: ProbeSnapshot,
    snap1: ProbeSnapshot | None,
    last: dict[str, Any],
    pkg: dict[str, Any],
) -> bool:
    expected = combined_notch_to_ipc_value(B1_NOTCH, pkg)
    if not last.get("ok"):
        return False
    sent = last.get("value")
    if sent is None or abs(float(sent) - expected) > 0.0001:
        return False
    lever1 = probe_lever(snap1)
    return _b1_brake_evidence(snap1, lever1, baseline=snap0)


def _fmt_ipc_result(result: dict[str, Any]) -> str:
    parts = [
        "ok" if result.get("ok") else "FAIL",
        f"err={result.get('error')}" if result.get("error") else "",
        f"ack={result.get('ack_ms', 0):.0f}ms" if result.get("ack_ms") else "",
        f"via={result.get('channel', 'ipc')}",
    ]
    ack = result.get("ack")
    if isinstance(ack, dict) and ack.get("cmd_id") is not None:
        parts.append(f"cmd_id={ack['cmd_id']}")
    return " ".join(p for p in parts if p)


def run_ipc_brake_test(*, interactive: bool = True) -> int:
    getdata = default_getdata_path()
    print("\n=== TSW6 V2 — prueba freno IPC (Lua, sin HTTP) ===\n")
    print("  Requisitos:")
    print("    • TSW6 en cabina (master key ON, MCB freno ON)")
    print("    • install_ue4ss_probe.bat → reiniciar TSW → probe ON")
    print(f"    • GetData: {getdata}")
    print(f"    • Bridge:  {bridge_dir()}\n")

    purge_lua_commands()
    snap = read_snapshot(getdata)
    if not is_probe_fresh(snap, path=getdata, stale_s=PROBE_STALE_S):
        print("  [FAIL] Probe no activo — F7 ON o reinstala mod (build 20260902b)")
        if snap is None:
            print(f"    No se lee {getdata}")
        else:
            print(f"    seq={snap.seq}  age>{PROBE_STALE_S}s o línea incompleta")
        return 1
    if snap is None:
        return 1

    lever0 = probe_lever(snap)
    pkg = _vehicle_package(snap)
    mc_mode = pkg is not None and uses_mc_analog_ipc(pkg)
    print_getdata_summary(snap, "Estado inicial (GetData)")
    if mc_mode:
        print(
            "\n  [INFO] MC US: B1/neutro vía fracción InputValue "
            f"(paquete {pkg.get('vehicle_id') if pkg else '?'}); "
            "lever_notch UK puede no coincidir."
        )
    elif _mc_vehicle_name_heuristic(snap):
        print(
            "\n  [AVISO] Parece MC US pero no hay paquete en data/vehicles/ "
            f"(vehicle={snap.vehicle!r}) — IPC usaría muesca/8 (323)."
        )

    mph0 = (snap.speed_ms or 0.0) * MS_TO_MPH if snap and snap.speed_ms is not None else 0.0
    if mph0 > 15.0:
        print(f"\n  [AVISO] Velocidad alta ({mph0:.0f} mph). Mejor parado o <15 mph.")

    if interactive:
        try:
            input("\n  Enter → enviar B1 vía IPC (muesca 3)… ")
        except EOFError:
            pass

    target = B1_NOTCH
    steps_est = ipc_steps_needed(lever0, target) if lever0 is not None else 0
    val = combined_notch_to_ipc_value(target, pkg)
    if mc_mode:
        print(
            f"\n  IPC → B1 (UK muesca {target}) InputValue={val:.3f} "
            f"(1 comando; lever_notch actual {lever0})"
        )
    else:
        print(
            f"\n  IPC → B1 muesca {target} (cmd={val:.3f}; "
            f"~{steps_est} paso(s) desde {lever0}; Lua 1 muesca/comando)"
        )
    if lever0 is not None and int(lever0) <= 3:
        print(
            "    (323: un paso desde muesca 2→3 usa OutputValue -1 en UE; "
            "es B1, no muesca negativa)"
        )
    ok_drive, snap1, results, n_sent = drive_to_notch(
        target,
        path=getdata,
        cmd_id_start=1,
        ack_timeout_s=IPC_ACK_TIMEOUT_S,
        vehicle=snap.vehicle,
    )
    last = results[-1] if results else {}
    print(f"    Comandos IPC:      {n_sent}  último: {_fmt_ipc_result(last)}")
    print_getdata_summary(snap1, "Tras B1 (GetData)")

    lever1 = probe_lever(snap1)
    train_brk = snap1.train_brake if snap1 else None
    moved = (
        lever0 is not None
        and lever1 is not None
        and int(lever1) != int(lever0)
    )
    at_target = lever1 is not None and int(lever1) == target
    brake_ok = _b1_brake_evidence(snap1, lever1, baseline=snap)
    ipc_ok = bool(last.get("ok"))

    if n_sent == 0 and at_target:
        print(
            "\n  [AVISO] 0 comandos IPC — la muesca ya era el objetivo "
            "(¿moviste la palanca antes del Enter?)"
        )

    ok = False
    mc_pass = (
        mc_mode
        and pkg is not None
        and _mc_b1_ipc_pass(snap, snap1, last, pkg)
    )
    if mc_pass:
        ok = True
        print(
            "\n  [PASS] B1 MC: IPC InputValue ok + efecto freno "
            f"(cilindro/HUD; lever_notch={lever1}, no muesca UK)"
        )
    elif ok_drive and at_target and moved and ipc_ok:
        ok = True
        if brake_ok:
            print("\n  [PASS] B1: IPC ok, muesca 3 (+ freno/cilindro coherente)")
        else:
            print(
                "\n  [PASS] B1: IPC ok, muesca 3 "
                f"(train_brake={fmt_num(train_brk)}; en MC el % HUD puede no "
                "reflejarse en GetData)"
            )
    elif mc_mode and pkg is not None and ipc_ok and not mc_pass:
        sent = last.get("value")
        exp = combined_notch_to_ipc_value(B1_NOTCH, pkg)
        print(
            f"\n  [FAIL] MC: ACK ok pero criterio B1 no cumplido "
            f"(enviado={sent}, esperado={exp:.3f}, brake_evidence={brake_ok})"
        )
        ok = False
    elif ok_drive and at_target and not moved:
        print(f"\n  [FAIL] lever sigue en {lever1} (IPC no movió la palanca)")
        ok = False
    elif not at_target and not mc_mode:
        print(
            f"\n  [FAIL] lever={lever1} (objetivo {target}; "
            f"desde {lever0} hacen falta ~{steps_est} pasos)"
        )
        ok = False
    else:
        print("\n  [FAIL] ACK Lua rechazado o timeout")
        err = str(last.get("error") or "")
        if err == "lua_rejected":
            print("    Lua no pudo escribir PBH — revisa UE4SS.log")
        elif err == "ack_timeout":
            print("    Sin ACK — ¿probe ON? ¿TSW6ApplyCommands.flag?")
        ok = False

    if interactive:
        try:
            input("\n  Enter → neutro vía IPC (muesca 4)… ")
        except EOFError:
            pass

    neutral = NEUTRAL_NOTCH
    neutral_val = combined_notch_to_ipc_value(neutral, pkg)
    if mc_mode:
        print(f"\n  IPC → neutro (UK muesca {neutral}) InputValue={neutral_val:.3f}")
    else:
        print(f"\n  IPC → neutro muesca {neutral}")
    _, snap2, release_results, n_rel = drive_to_notch(
        neutral,
        path=getdata,
        cmd_id_start=20,
        ack_timeout_s=IPC_ACK_TIMEOUT_S,
        vehicle=snap.vehicle,
    )
    rel_last = release_results[-1] if release_results else {}
    print(f"    Comandos IPC:      {n_rel}  último: {_fmt_ipc_result(rel_last)}")
    print_getdata_summary(snap2, "Tras neutro (GetData)")
    purge_lua_commands()
    return 0 if ok else 1
