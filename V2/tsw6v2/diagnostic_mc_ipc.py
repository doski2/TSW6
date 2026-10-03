"""Prueba IPC analog MasterController (0..1) en cabina."""

from __future__ import annotations

from tsw6v2.bridge.getdata import default_getdata_path
from tsw6v2.bridge.ipc_bus import (
    bridge_dir,
    dispatch_ipc_master_controller,
    purge_lua_commands,
)
from tsw6v2.constants import IPC_ACK_TIMEOUT_S, PROBE_STALE_S
from tsw6v2.diagnostic import _fmt_ipc_result
from tsw6v2.probe import is_probe_fresh, print_getdata_summary, read_snapshot


def run_mc_analog_ipc_test(*, interactive: bool = True) -> int:
    getdata = default_getdata_path()
    print("\n=== TSW6 V2 — prueba IPC MC analog (0..1) ===\n")
    print("  Requisitos: probe 20261003b+, M3a/M7a, F7 ON, Explorer OFF")
    print(f"  GetData: {getdata}")
    print(f"  Bridge:  {bridge_dir()}\n")

    purge_lua_commands()
    snap = read_snapshot(getdata)
    if not is_probe_fresh(snap, path=getdata, stale_s=PROBE_STALE_S):
        print("  [FAIL] Probe no activo")
        return 1

    print_getdata_summary(snap, "Estado inicial")
    targets = (
        (0.72, "neutro ~0.72 (lab M3a)"),
        (0.85, "freno ligero ~0.85"),
        (0.72, "volver neutro"),
    )
    ok_all = True
    cmd_id = 1
    for fraction, label in targets:
        if interactive:
            try:
                input(f"\n  Enter → IPC InputValue {fraction:.2f} ({label})… ")
            except EOFError:
                pass
        print(f"\n  IPC → PowerBrakeHandle (MC analog) = {fraction:.2f}")
        result = dispatch_ipc_master_controller(
            fraction,
            cmd_id=cmd_id,
            ack_timeout_s=IPC_ACK_TIMEOUT_S,
        )
        print(f"    {_fmt_ipc_result(result)}")
        snap = read_snapshot(getdata)
        print_getdata_summary(snap, "Tras comando")
        ok_all = ok_all and bool(result.get("ok"))
        cmd_id += 1

    purge_lua_commands()
    if ok_all:
        print("\n  [PASS] IPC MC analog (ACK ok en todos los pasos)")
        return 0
    print("\n  [FAIL] Algún ACK rechazado — revisa UE4SS.log")
    return 1
