"""Diagnósticos in-game (test IPC B1)."""

from __future__ import annotations

from typing import Any

from tsw6v2.bridge.commands import combined_notch_to_value
from tsw6v2.bridge.getdata import default_getdata_path
from tsw6v2.bridge.ipc_bus import bridge_dir, purge_lua_commands
from tsw6v2.constants import (
    B1_MIN_TRAIN_BRAKE,
    B1_NOTCH,
    IPC_ACK_TIMEOUT_S,
    MS_TO_MPH,
    NEUTRAL_NOTCH,
    PROBE_STALE_S,
)
from tsw6v2.ipc import drive_to_notch, ipc_steps_needed, probe_lever
from tsw6v2.probe import fmt_num, is_probe_fresh, print_getdata_summary, read_snapshot


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

    lever0 = probe_lever(snap)
    print_getdata_summary(snap, "Estado inicial (GetData)")

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
    val = combined_notch_to_value(target)
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
    brake_ok = train_brk is not None and float(train_brk) >= B1_MIN_TRAIN_BRAKE

    if ok_drive and at_target and brake_ok and moved:
        print("\n  [PASS] B1: lever=3 y train_brake≥0.25")
        ok = True
    elif at_target and not brake_ok:
        print(
            f"\n  [FAIL] lever={lever1} pero train_brake="
            f"{fmt_num(train_brk)} (esperado ≥{B1_MIN_TRAIN_BRAKE:.2f})"
        )
        ok = False
    elif ok_drive and at_target and not moved:
        print(f"\n  [FAIL] lever sigue en {lever1} (IPC no movió la palanca)")
        ok = False
    elif not at_target:
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
    print(f"\n  IPC → neutro muesca {neutral}")
    _, snap2, release_results, n_rel = drive_to_notch(
        neutral,
        path=getdata,
        cmd_id_start=20,
        ack_timeout_s=IPC_ACK_TIMEOUT_S,
    )
    rel_last = release_results[-1] if release_results else {}
    print(f"    Comandos IPC:      {n_rel}  último: {_fmt_ipc_result(rel_last)}")
    print_getdata_summary(snap2, "Tras neutro (GetData)")
    purge_lua_commands()
    return 0 if ok else 1
