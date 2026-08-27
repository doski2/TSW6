"""
TSW6 API Monitor - Lectura de telemetría en tiempo real + prueba de freno HTTP.

Requiere: TSW6 corriendo con -HTTPAPI  |  pip install requests colorama

Modos: monitor | test-brake | test-ipc | discover | snapshot | raw
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from tsw6.paths import PROJECT_ROOT

try:
    from colorama import Fore, Style, init  # type: ignore[assignment]

    init(autoreset=True)
    COLOR = True
except ImportError:
    COLOR = False

    class Fore:
        GREEN = RED = YELLOW = CYAN = MAGENTA = WHITE = RESET = ""

    class Style:
        BRIGHT = RESET_ALL = ""

from tsw6.telemetry.tsw_api_client import (
    TswApiClient,
    api_driver_input_path,
    encode_control_path,
    find_api_key,
    get_key_path,
)
from tsw6.telemetry.tsw_command_bus import (
    combined_notch_to_value,
    dispatch_combined_notch,
)
from tsw6.telemetry.tsw_fast_telemetry import FastControlReader
from tsw6.telemetry.tsw_ipc_bus import (
    bridge_dir,
    dispatch_ipc_combined_notch,
    enable_lua_commands,
    purge_lua_commands,
)
from tsw6.telemetry.tsw_ue4ss_reader import (
    ProbeSnapshot,
    default_getdata_path,
    read_probe_file,
)

DRIVABLE = "CurrentDrivableActor"
DEFAULT_INTERVAL = 0.15
META_REFRESH_S = 30.0
SLOW_REFRESH_TICKS = 5

# Lecturas cada ciclo (velocidad / mandos)
FAST_HUD_READS: tuple[tuple[str, str], ...] = (
    ("speed", f"{DRIVABLE}.Function.HUD_GetSpeed"),
    ("power", f"{DRIVABLE}.Function.HUD_GetPowerHandle"),
    ("train_brake", f"{DRIVABLE}.Function.HUD_GetTrainBrakeHandle"),
    ("accel", f"{DRIVABLE}.Function.HUD_GetAcceleration"),
)

# Lecturas menos críticas (nombre tren, límite, frenos extra)
SLOW_HUD_READS: tuple[tuple[str, str], ...] = (
    ("object_class", f"{DRIVABLE}.ObjectClass"),
    ("max_speed", f"{DRIVABLE}.Function.HUD_GetMaxPermittedSpeed"),
    ("loco_brake", f"{DRIVABLE}.Function.HUD_GetLocomotiveBrakeHandle"),
    ("dyn_brake", f"{DRIVABLE}.Function.HUD_GetElectricBrakeHandle"),
)

HUD_READS: tuple[tuple[str, str], ...] = FAST_HUD_READS + SLOW_HUD_READS


def color(text: str, c: str) -> str:
    return f"{c}{text}{Style.RESET_ALL}" if COLOR else text


def fmt_speed(mps: Optional[float]) -> str:
    """Convierte m/s a km/h."""
    if mps is None:
        return "?"
    kmh = mps * 3.6
    if kmh > 0:
        return color(f"{kmh:5.1f} km/h", Fore.GREEN)
    return color(f"{kmh:5.1f} km/h", Fore.WHITE)


def fmt_bar(value: float, width: int = 20, active: str = "█", empty: str = "░") -> str:
    filled = max(0, min(int(value * width), width))
    return active * filled + empty * (width - filled)


def _fetch_nodes(client: TswApiClient, paths: dict[str, str]) -> dict[str, Optional[dict[str, Any]]]:
    """
    Lee nodos en serie sobre la misma sesión HTTP.
    La API TSW penaliza ~2 s la primera petición de cada ráfaga; las siguientes ~15 ms.
    """
    out: dict[str, Optional[dict[str, Any]]] = {}
    for name, path in paths.items():
        out[name] = client.get_node(path)
    return out


def _vehicle_from_hud(hud: dict[str, Optional[dict[str, Any]]], vehicle: dict[str, Any]) -> dict[str, Any]:
    """Fusiona lecturas HUD en el dict vehicle (conserva valores previos si falla una lectura)."""
    object_class = hud.get("object_class")
    if object_class is not None:
        vehicle["class"] = object_class.get("ObjectClass", vehicle.get("class", "?"))

    speed_vals = hud.get("speed") or {}
    if "Speed (ms)" in speed_vals:
        vehicle["speed_ms"] = speed_vals.get("Speed (ms)")

    max_vals = hud.get("max_speed") or {}
    if max_vals:
        vehicle["max_speed_ms"] = max_vals.get("MaxSpeed (ms)")
        vehicle["max_speed_active"] = max_vals.get("IsActive", False)

    power_vals = hud.get("power") or {}
    if power_vals:
        vehicle["power"] = power_vals.get("Power")
        vehicle["power_active"] = power_vals.get("IsActive", False)
        vehicle["power_negative"] = power_vals.get("IsNegative", False)

    train_brake = hud.get("train_brake") or {}
    if train_brake and "HandlePosition" in train_brake:
        vehicle["train_brake"] = train_brake.get("HandlePosition")

    loco_brake = hud.get("loco_brake") or {}
    if loco_brake:
        vehicle["loco_brake"] = loco_brake.get("HandlePosition")
        vehicle["loco_brake_active"] = loco_brake.get("IsActive", False)

    dyn_brake = hud.get("dyn_brake") or {}
    if dyn_brake:
        vehicle["dyn_brake"] = dyn_brake.get("HandlePosition")
        vehicle["dyn_brake_active"] = dyn_brake.get("IsActive", False)

    accel_vals = hud.get("accel") or {}
    if "Acceleration (ms2)" in accel_vals:
        vehicle["accel_ms2"] = accel_vals.get("Acceleration (ms2)")

    return vehicle


class TelemetryPoller:
    """Estado del monitor: reutiliza FastControlReader para el bucle rápido."""

    def __init__(self) -> None:
        self.tick = 0
        self.meta: dict[str, Any] = {}
        self.vehicle: dict[str, Any] = {"class": "?"}
        self.in_cab = False
        self._meta_at = 0.0
        self._reader: Optional[FastControlReader] = None

    def _ensure_reader(self, client: TswApiClient) -> FastControlReader:
        if self._reader is None:
            self._reader = FastControlReader(client)
            self._reader.setup()
        return self._reader

    def _refresh_meta_if_needed(self, client: TswApiClient, force: bool = False) -> None:
        now = time.monotonic()
        if not force and self.meta and (now - self._meta_at) < META_REFRESH_S:
            return
        info = client.get_json("/info")
        if isinstance(info, dict):
            self.meta = info.get("Meta") or {}
            self._meta_at = now

    def poll(self, client: TswApiClient, *, full: bool = False) -> dict[str, Any]:
        self.tick += 1
        self._refresh_meta_if_needed(client, force=full or self.tick == 1)

        reader = self._ensure_reader(client)
        snap = reader.read()

        if snap.speed_ms is not None:
            self.in_cab = True
            vehicle = dict(self.vehicle)
            vehicle["speed_ms"] = snap.speed_ms
            if snap.power is not None:
                vehicle["power"] = snap.power
                vehicle["power_negative"] = snap.power_negative
                vehicle["power_active"] = True
            if snap.train_brake is not None:
                vehicle["train_brake"] = snap.train_brake
            if snap.accel_ms2 is not None:
                vehicle["accel_ms2"] = snap.accel_ms2
            vehicle["telemetry_source"] = snap.source
            vehicle["telemetry_age_ms"] = snap.age_ms
            self.vehicle = vehicle
        elif self.tick == 1 or full:
            self.in_cab = False

        if full or self.tick == 1 or self.tick % SLOW_REFRESH_TICKS == 0:
            hud_slow = _fetch_nodes(client, dict(SLOW_HUD_READS))
            if hud_slow.get("object_class") is not None:
                self.in_cab = True
            merged = _vehicle_from_hud(hud_slow, dict(self.vehicle))
            if snap.speed_ms is not None:
                merged["speed_ms"] = snap.speed_ms
                if snap.power is not None:
                    merged["power"] = snap.power
                    merged["power_negative"] = snap.power_negative
                    merged["power_active"] = True
                if snap.train_brake is not None:
                    merged["train_brake"] = snap.train_brake
                if snap.accel_ms2 is not None:
                    merged["accel_ms2"] = snap.accel_ms2
            merged["telemetry_source"] = snap.source
            merged["telemetry_age_ms"] = snap.age_ms
            self.vehicle = merged

        return {
            "meta": dict(self.meta),
            "in_cab": self.in_cab,
            "vehicle": dict(self.vehicle) if self.in_cab else {},
        }


def collect_telemetry(client: TswApiClient) -> dict[str, Any]:
    """Recopila meta del juego y telemetría del actor en cabina (snapshot completo)."""
    poller = TelemetryPoller()
    return poller.poll(client, full=True)


def print_dashboard(data: dict[str, Any], *, refresh_hz: Optional[float] = None, interval: float = DEFAULT_INTERVAL) -> None:
    """Imprime el dashboard en consola."""
    os.system("cls" if sys.platform == "win32" else "clear")

    print(color("═" * 60, Fore.CYAN))
    print(
        color(
            "  🚂  TSW6 MONITOR  —  " + datetime.now().strftime("%H:%M:%S"),
            Fore.CYAN + Style.BRIGHT,
        )
    )
    print(color("═" * 60, Fore.CYAN))

    meta = data.get("meta") or {}
    if meta:
        print(f"\n{color('JUEGO', Fore.YELLOW + Style.BRIGHT)}")
        print(f"  Nombre   : {meta.get('GameName', '?')}")
        print(f"  Build    : {meta.get('GameBuildNumber', '?')}")
        print(f"  API      : v{meta.get('APIVersion', '?')}")

    if not data.get("in_cab"):
        print(f"\n{color('CABINA', Fore.YELLOW + Style.BRIGHT)}")
        print(color("  Sin datos de cabina — carga un escenario y sube al tren.", Fore.YELLOW))
    else:
        vehicle = data.get("vehicle") or {}
        print(f"\n{color('TREN', Fore.YELLOW + Style.BRIGHT)}")
        print(f"  Vehículo : {vehicle.get('class', '?')}")

        speed = vehicle.get("speed_ms")
        print(f"  Velocidad: {fmt_speed(speed)}", end="")
        max_speed = vehicle.get("max_speed_ms")
        if vehicle.get("max_speed_active") and isinstance(max_speed, (int, float)) and max_speed > 0:
            if isinstance(speed, (int, float)) and speed > max_speed:
                print(f"  {color('⚠ EXCESO', Fore.RED + Style.BRIGHT)}", end="")
            print()
            print(f"  Límite   : {fmt_speed(max_speed)}")
        else:
            print()

        accel = vehicle.get("accel_ms2")
        if isinstance(accel, (int, float)):
            label = color("frenando", Fore.RED) if accel < -0.05 else color("acelerando", Fore.GREEN) if accel > 0.05 else "estable"
            print(f"  Acel.    : {accel:+.2f} m/s² ({label})")

        power = vehicle.get("power")
        if isinstance(power, (int, float)):
            side = "freno" if vehicle.get("power_negative") else "tracción"
            bar = fmt_bar(abs(power))
            tint = Fore.RED if vehicle.get("power_negative") else Fore.GREEN
            active = "" if vehicle.get("power_active", True) else color(" (inactivo)", Fore.WHITE)
            print(f"  Mando    : [{color(bar, tint)}] {power:.2f} ({side}){active}")

        train_brake = vehicle.get("train_brake")
        if isinstance(train_brake, (int, float)):
            bar = fmt_bar(abs(train_brake))
            print(f"  Freno tren: [{color(bar, Fore.RED)}] {train_brake:.2f}")

        if vehicle.get("loco_brake_active"):
            loco = vehicle.get("loco_brake")
            if isinstance(loco, (int, float)):
                bar = fmt_bar(abs(loco))
                print(f"  Freno loco: [{color(bar, Fore.RED)}] {loco:.2f}")

        if vehicle.get("dyn_brake_active"):
            dyn = vehicle.get("dyn_brake")
            if isinstance(dyn, (int, float)) and abs(dyn) > 0.01:
                bar = fmt_bar(abs(dyn))
                print(f"  Freno din.: [{color(bar, Fore.MAGENTA)}] {dyn:.2f}")

    hz_text = f"{refresh_hz:.1f} Hz" if refresh_hz and refresh_hz > 0 else "—"
    vehicle = data.get("vehicle") or {}
    src = vehicle.get("telemetry_source")
    age = vehicle.get("telemetry_age_ms")
    src_text = ""
    if src:
        src_text = f"  |  {src}"
        if isinstance(age, (int, float)):
            src_text += f" {age:.0f}ms"
    print(f"\n{color('─' * 60, Fore.CYAN)}")
    print(
        color(
            f"  Ctrl+C para salir  |  objetivo {interval:.1f}s  |  {hz_text}{src_text}",
            Fore.WHITE,
        )
    )


def discover_endpoints(client: TswApiClient) -> dict[str, Any]:
    """Lista rutas HTTP y endpoints HUD del actor en cabina."""
    print(color("\n🔍 Explorando API TSW6...\n", Fore.CYAN))
    results: dict[str, Any] = {}

    info = client.get_json("/info")
    if info is not None:
        results["info"] = info
        print(color("  /info", Fore.GREEN) + "  ✓ OK")
        for route in info.get("HttpRoutes", []):
            print(f"    {route.get('Verb', '?'):6s} {route.get('Path', '?')}")
    else:
        print(color("  /info", Fore.RED) + "  ✗ N/A")

    print()
    actor = client.list_node(DRIVABLE)
    if isinstance(actor, dict) and actor.get("Result") == "Success":
        results["drivable_actor"] = actor
        endpoints = actor.get("Endpoints") or []
        print(color(f"  /list/{DRIVABLE}", Fore.GREEN) + f"  ✓ {len(endpoints)} endpoints")
        hud = [e.get("Name") for e in endpoints if isinstance(e, dict) and str(e.get("Name", "")).startswith("Function.HUD_")]
        for name in hud[:20]:
            print(f"    {name}")
        if len(hud) > 20:
            print(f"    ... y {len(hud) - 20} más")
    else:
        print(color(f"  /list/{DRIVABLE}", Fore.RED) + "  ✗ sin cabina o sin escenario")

    print()
    sample = collect_telemetry(client)
    if sample.get("in_cab"):
        results["telemetry_sample"] = sample
        print(color("  Telemetría HUD", Fore.GREEN) + "  ✓ OK")
    else:
        print(color("  Telemetría HUD", Fore.YELLOW) + "  — entra en cabina para leer mandos")

    print()
    return results


def monitor_loop(client: TswApiClient, key_path: Path, interval: float = DEFAULT_INTERVAL) -> None:
    """Bucle principal de monitorización en tiempo real."""
    last_key_mtime = key_path.stat().st_mtime
    poller = TelemetryPoller()
    connected = False

    print(color("\n▶ Iniciando monitor... (Ctrl+C para salir)\n", Fore.GREEN))
    time.sleep(0.2)

    try:
        while True:
            loop_start = time.perf_counter()
            current_mtime = key_path.stat().st_mtime
            if current_mtime != last_key_mtime:
                key = key_path.read_text(encoding="utf-8").strip()
                client = TswApiClient(key, session=client._session, timeout=client.timeout)
                last_key_mtime = current_mtime
                poller = TelemetryPoller()
                connected = False
                print(color("  🔑 API key actualizada automáticamente", Fore.YELLOW))

            data = poller.poll(client)
            elapsed = time.perf_counter() - loop_start
            refresh_hz = 1.0 / elapsed if elapsed > 0 else None

            if data.get("in_cab") or poller.meta:
                connected = True
                print_dashboard(data, refresh_hz=refresh_hz, interval=interval)
            elif connected:
                print_dashboard(data, refresh_hz=refresh_hz, interval=interval)
            else:
                os.system("cls" if sys.platform == "win32" else "clear")
                print(color("\n  ⏳ Esperando a que TSW6 esté disponible...", Fore.YELLOW))
                print(color("  Asegúrate de:", Fore.WHITE))
                print("    1. TSW6 corriendo con -HTTPAPI en los argumentos de Steam")
                print("    2. Haber cargado un escenario (no en el menú principal)")

            sleep_s = max(0.05, interval - elapsed)
            time.sleep(sleep_s)

    except KeyboardInterrupt:
        print(color("\n\nMonitor detenido.\n", Fore.YELLOW))


def _fmt_patch_result(result: dict[str, Any]) -> str:
    parts = [str(result.get("error") or ("ok" if result.get("ok") else "?"))]
    if result.get("message"):
        parts.append(f"msg={result['message']}")
    if result.get("via"):
        parts.append(f"via={result['via']}")
    if result.get("hud_notch") is not None:
        parts.append(f"hud={result['hud_notch']}")
    if result.get("target_notch") is not None:
        parts.append(f"tgt={result['target_notch']}")
    return " ".join(parts)


def _read_input_raw(client: TswApiClient, control: str) -> Any:
    """GET crudo de InputValue (incluye Result/Message si la API falla)."""
    api_path = api_driver_input_path(control)
    encoded = encode_control_path(f"{api_path}.InputValue")
    return client.get_json(f"/get/{encoded}")


def test_brake(client: TswApiClient) -> int:
    """
    Prueba escritura HTTP del freno combinado UK (V2.3).

    Misma ruta que el autopilot: dispatch_combined_notch → DriverInput.PowerBrakeHandle.
    """
    print(color("\n🧪 Prueba de freno HTTP (Class 323 / combined)\n", Fore.CYAN))
    print("  Tren en cabina, master key ON, MCB freno ON.")
    print("  Recomendado: parado o velocidad baja antes de pulsar Enter.\n")

    if not client.probe():
        print(color("  ✗ API no responde — arranca TSW6 con -HTTPAPI", Fore.RED))
        return 1

    # Calentar sesión HTTP (primera petición ~2 s en TSW)
    _fetch_nodes(client, dict(FAST_HUD_READS))
    hud0 = client.read_hud_combined_notch()
    pbh_in = client.get_input_value("PowerBrakeHandle")
    pbh_raw = _read_input_raw(client, "PowerBrakeHandle")
    master = client.get_input_value("MasterKey")

    print(color("  Estado inicial", Fore.WHITE))
    print(f"    HUD muesca UK:     {hud0 if hud0 is not None else '?'}")
    print(f"    PBH InputValue:    {pbh_in if pbh_in is not None else '?'}")
    print(f"    MasterKey:         {master if master is not None else '?'}")
    if isinstance(pbh_raw, dict) and pbh_raw.get("Result") != "Success":
        print(color(f"    GET PBH raw:       {pbh_raw}", Fore.YELLOW))

    try:
        input(color("\n  Enter → enviar B1 (muesca 3)… ", Fore.GREEN))
    except EOFError:
        pass

    target = 3
    val = combined_notch_to_value(target)
    print(color(f"\n  PATCH combined → muesca {target} (cmd={val:.3f})", Fore.CYAN))
    result = dispatch_combined_notch(client, target, timeout=4.0)
    print(f"    Resultado: {_fmt_patch_result(result)}")
    if not result.get("ok") and result.get("body"):
        print(f"    Body: {str(result.get('body'))[:200]}")

    time.sleep(0.35)
    hud1 = client.read_hud_combined_notch()
    pbh1 = client.get_input_value("PowerBrakeHandle")
    print(color("\n  Tras B1", Fore.WHITE))
    print(f"    HUD muesca UK:     {hud1 if hud1 is not None else '?'}")
    print(f"    PBH InputValue:    {pbh1 if pbh1 is not None else '?'}")

    moved = (
        hud0 is not None and hud1 is not None and int(hud1) != int(hud0)
    )
    on_target = hud1 is not None and abs(int(hud1) - int(target)) <= 1
    patch_ok = bool(result.get("ok"))

    if patch_ok and on_target and moved:
        print(color("\n  ✓ PASS — PATCH ok y HUD en muesca objetivo", Fore.GREEN))
        ok = True
    elif on_target and not moved:
        print(color(
            f"\n  ✗ FAIL — HUD sigue en {hud1} (sin movimiento; PATCH no tuvo efecto)",
            Fore.RED,
        ))
        ok = False
    elif patch_ok:
        print(color("\n  ~ WARN — PATCH ok pero HUD no confirma muesca", Fore.YELLOW))
        ok = False
    else:
        print(color("\n  ✗ FAIL — PATCH rechazado o sin efecto", Fore.RED))
        ok = False
        if str(result.get("message") or "") == "Not Set":
            print(color(
                "    DriverInput no enlazado — HTTP no puede escribir la palanca.",
                Fore.YELLOW,
            ))
        if isinstance(pbh_raw, dict) and "failed to return valid data" in str(
            pbh_raw.get("Message", "")
        ):
            print(color(
                "    El juego acepta mandos por teclas A/D (SendInput) — mismo path que jugador.",
                Fore.CYAN,
            ))

    try:
        input(color("\n  Enter → neutro (muesca 4)… ", Fore.GREEN))
    except EOFError:
        pass

    neutral = 4
    print(color(f"\n  PATCH → muesca {neutral} (neutro)", Fore.CYAN))
    release = dispatch_combined_notch(client, neutral, timeout=4.0)
    print(f"    Resultado: {_fmt_patch_result(release)}")
    hud2 = client.read_hud_combined_notch()
    print(f"    HUD final:         {hud2 if hud2 is not None else '?'}\n")
    return 0 if ok else 1


PROBE_STALE_S = 2.5
IPC_TEST_ACK_TIMEOUT_S = 0.35
IPC_TEST_LEVER_WAIT_S = 2.5


def _probe_snapshot() -> Optional[ProbeSnapshot]:
    return read_probe_file(default_getdata_path())


def _probe_is_fresh(snap: Optional[ProbeSnapshot]) -> bool:
    if snap is None or snap.seq is None or snap.speed_ms is None:
        return False
    path = default_getdata_path()
    if not path.is_file():
        return False
    try:
        return (time.time() - path.stat().st_mtime) <= PROBE_STALE_S
    except OSError:
        return False


def _probe_lever(snap: Optional[ProbeSnapshot] = None) -> Optional[int]:
    snap = snap if snap is not None else _probe_snapshot()
    if snap is None:
        return None
    return snap.combined_handle_notch()


def _wait_probe_lever(
    target: int,
    *,
    timeout_s: float = IPC_TEST_LEVER_WAIT_S,
) -> tuple[bool, Optional[int]]:
    deadline = time.monotonic() + timeout_s
    last: Optional[int] = None
    while time.monotonic() < deadline:
        snap = _probe_snapshot()
        last = _probe_lever(snap)
        if last is not None and abs(int(last) - int(target)) <= 1:
            return True, last
        time.sleep(0.05)
    return False, last


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


def test_ipc() -> int:
    """
    Prueba mandos solo por IPC (SendCommand.txt → Lua → UE).

    Sin HTTP ni teclado. Requiere probe UE4SS build ``n`` (sin SetCurrentNotchIndex).
    """
    getdata = default_getdata_path()
    print(color("\n🧪 Prueba de freno IPC (Lua → UE, sin HTTP)\n", Fore.CYAN))
    print("  Requisitos:")
    print("    • TSW6 en cabina (master key ON, MCB freno ON)")
    print("    • install_ue4ss_probe.bat  →  reiniciar TSW  →  F7 ON")
    print(f"    • GetData activo: {getdata}")
    print(f"    • Bridge IPC:     {bridge_dir()}\n")

    purge_lua_commands()
    snap = _probe_snapshot()
    if not _probe_is_fresh(snap):
        print(color(
            "  ✗ Probe no activo — F7 ON en cabina o reinstala el mod (build 20260827n)",
            Fore.RED,
        ))
        if snap is None:
            print(f"    No se lee {getdata}")
        else:
            print(f"    seq={snap.seq}  age>{PROBE_STALE_S}s o línea incompleta")
        return 1

    lever0 = _probe_lever(snap)
    print(color("  Estado inicial (GetData)", Fore.WHITE))
    print(f"    lever_notch:       {lever0 if lever0 is not None else '?'}")
    print(f"    seq:               {snap.seq if snap else '?'}")
    print(f"    last_cmd_id:       {snap.last_cmd_id if snap else '?'}")
    print(f"    last_ack_ok:       {snap.last_ack_ok if snap else '?'}")

    try:
        input(color("\n  Enter → enviar B1 vía IPC (muesca 3)… ", Fore.GREEN))
    except EOFError:
        pass

    target = 3
    cmd_id = 1
    val = combined_notch_to_value(target)
    enable_lua_commands()
    print(color(
        f"\n  IPC SendCommand → muesca {target} (cmd={val:.3f} id={cmd_id})",
        Fore.CYAN,
    ))
    result = dispatch_ipc_combined_notch(
        target,
        cmd_id=cmd_id,
        ack_timeout_s=IPC_TEST_ACK_TIMEOUT_S,
    )
    print(f"    Resultado:         {_fmt_ipc_result(result)}")

    time.sleep(0.08)
    snap1 = _probe_snapshot()
    lever1 = _probe_lever(snap1)
    on_target, lever_after = _wait_probe_lever(target)
    if lever_after is not None:
        lever1 = lever_after

    print(color("\n  Tras B1 (GetData)", Fore.WHITE))
    print(f"    lever_notch:       {lever1 if lever1 is not None else '?'}")
    if snap1:
        print(f"    last_cmd_id:       {snap1.last_cmd_id}")
        print(f"    last_ack_ok:       {snap1.last_ack_ok}")

    moved = (
        lever0 is not None
        and lever1 is not None
        and int(lever1) != int(lever0)
    )
    ack_ok = bool(result.get("ok"))
    at_target = lever1 is not None and abs(int(lever1) - int(target)) <= 1

    if ack_ok and at_target and moved:
        print(color("\n  ✓ PASS — ACK Lua ok y lever_notch en objetivo", Fore.GREEN))
        ok = True
    elif at_target and not moved:
        print(color(
            f"\n  ✗ FAIL — lever sigue en {lever1} (IPC no movió la palanca)",
            Fore.RED,
        ))
        ok = False
    elif ack_ok and not at_target:
        print(color(
            f"\n  ~ WARN — ACK ok pero lever={lever1} (objetivo {target})",
            Fore.YELLOW,
        ))
        if not on_target:
            print(color(
                "    Revisa UE4SS.log: IPC write PBH / PBH write OK",
                Fore.YELLOW,
            ))
        ok = False
    else:
        print(color("\n  ✗ FAIL — ACK Lua rechazado o timeout", Fore.RED))
        err = str(result.get("error") or "")
        if err == "lua_rejected":
            print(color(
                "    Lua no pudo escribir PowerBrakeHandle — F9 dump en cabina",
                Fore.YELLOW,
            ))
        elif err == "ack_timeout":
            print(color(
                "    Sin ACK — ¿F7 ON? ¿flag TSW6ApplyCommands.flag?",
                Fore.YELLOW,
            ))
        ok = False

    try:
        input(color("\n  Enter → neutro vía IPC (muesca 4)… ", Fore.GREEN))
    except EOFError:
        pass

    neutral = 4
    enable_lua_commands()
    print(color(f"\n  IPC → muesca {neutral} (neutro)", Fore.CYAN))
    release = dispatch_ipc_combined_notch(
        neutral,
        cmd_id=2,
        ack_timeout_s=IPC_TEST_ACK_TIMEOUT_S,
    )
    print(f"    Resultado:         {_fmt_ipc_result(release)}")
    _wait_probe_lever(neutral, timeout_s=1.5)
    lever2 = _probe_lever()
    print(f"    lever_notch final: {lever2 if lever2 is not None else '?'}\n")
    purge_lua_commands()
    return 0 if ok else 1


def save_snapshot(client: TswApiClient, filename: str = "tsw_snapshot.json") -> dict[str, Any]:
    """Guarda una captura de telemetría en JSON."""
    data = collect_telemetry(client)
    data["timestamp"] = datetime.now().isoformat()

    out = PROJECT_ROOT / filename
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(color(f"\n✓ Snapshot guardado en: {out}\n", Fore.GREEN))
    return data


def _parse_args() -> tuple[str, float]:
    modo = "monitor"
    interval = DEFAULT_INTERVAL
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in (
            "discover", "snapshot", "raw", "monitor",
            "test-brake", "test_brake", "test-ipc", "test_ipc",
        ):
            modo = arg.replace("_", "-")
        elif arg in ("--interval", "-i"):
            i += 1
            if i < len(args):
                interval = max(0.1, float(args[i]))
        elif arg.startswith("--interval="):
            interval = max(0.1, float(arg.split("=", 1)[1]))
        i += 1
    return modo, interval


if __name__ == "__main__":
    print(color("\n" + "═" * 60, Fore.CYAN))
    print(color("  TSW6 API MONITOR  |  API externa Dovetail", Fore.CYAN))
    print(color("═" * 60 + "\n", Fore.CYAN))

    modo, interval = _parse_args()

    if modo == "test-ipc":
        sys.exit(test_ipc())

    key = find_api_key()
    key_path = get_key_path()
    if not key or key_path is None:
        print(color("  ✗ No se encontró CommAPIKey.txt", Fore.RED))
        print("  Inicia TSW6 con -HTTPAPI al menos una vez para generarla.")
        sys.exit(1)

    print(color(f"  ✓ Key encontrada en: {key_path}", Fore.GREEN))
    print(color(f"  ✓ Key: {key[:10]}...{key[-5:]}", Fore.GREEN))

    client = TswApiClient(key, timeout=4.0)

    if modo == "discover":
        datos = discover_endpoints(client)
        sample = datos.get("telemetry_sample")
        if sample:
            print(color("Muestra de telemetría:\n", Fore.CYAN))
            print(json.dumps(sample, indent=2, ensure_ascii=False)[:2500])

    elif modo == "snapshot":
        save_snapshot(client)

    elif modo == "raw":
        try:
            while True:
                payload = collect_telemetry(client)
                payload["timestamp"] = datetime.now().isoformat()
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                time.sleep(interval)
        except KeyboardInterrupt:
            pass

    elif modo == "test-brake":
        sys.exit(test_brake(client))

    else:
        monitor_loop(client, key_path, interval=interval)
