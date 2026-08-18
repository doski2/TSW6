"""
TSW6 API Monitor - Lectura de telemetría en tiempo real
Requiere: TSW6 corriendo con -HTTPAPI  |  pip install requests colorama
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

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

from tsw_api_client import TswApiClient, find_api_key, get_key_path
from tsw_fast_telemetry import FastControlReader

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


def save_snapshot(client: TswApiClient, filename: str = "tsw_snapshot.json") -> dict[str, Any]:
    """Guarda una captura de telemetría en JSON."""
    data = collect_telemetry(client)
    data["timestamp"] = datetime.now().isoformat()

    out = Path(__file__).parent / filename
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
        if arg in ("discover", "snapshot", "raw", "monitor"):
            modo = arg
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

    key = find_api_key()
    key_path = get_key_path()
    if not key or key_path is None:
        print(color("  ✗ No se encontró CommAPIKey.txt", Fore.RED))
        print("  Inicia TSW6 con -HTTPAPI al menos una vez para generarla.")
        sys.exit(1)

    print(color(f"  ✓ Key encontrada en: {key_path}", Fore.GREEN))
    print(color(f"  ✓ Key: {key[:10]}...{key[-5:]}", Fore.GREEN))

    client = TswApiClient(key, timeout=4.0)
    modo, interval = _parse_args()

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

    else:
        monitor_loop(client, key_path, interval=interval)
