"""
TSW6 API Monitor - Lectura de telemetría en tiempo real
Requiere: TSW6 corriendo con -HTTPAPI  |  pip install requests colorama
"""

import requests
import time
import os
import sys
import json
from pathlib import Path
from datetime import datetime

try:
    from colorama import init, Fore, Style  # type: ignore[assignment]
    init(autoreset=True)
    COLOR = True
except ImportError:
    COLOR = False
    class Fore:
        GREEN = RED = YELLOW = CYAN = MAGENTA = WHITE = RESET = ""
    class Style:
        BRIGHT = RESET_ALL = ""

# ──────────────────────────────────────────────
# Rutas donde TSW guarda la API key según plataforma
# ──────────────────────────────────────────────
KEY_PATHS = [
    Path.home() / "Documents/My Games/TrainSimWorld6/Saved/Config/CommAPIKey.txt",
    Path.home() / "Documents/My Games/TrainSimWorld6EGS/Saved/Config/CommAPIKey.txt",
    Path.home() / "Documents/My Games/TrainSimWorld6WGDK/Saved/Config/CommAPIKey.txt",
    Path.home() / "OneDrive/Documents/My Games/TrainSimWorld6/Saved/Config/CommAPIKey.txt",
]

TSW_API = "http://localhost:31270"

# Endpoints conocidos de la API de TSW6
ENDPOINTS = {
    "info":           "/info",
    "run_info":       "/runInfo",
    "vehicles":       "/vehicles",
    "displayed":      "/displayedSpeeds",
    "player":         "/player",
    "timetable":      "/timetable",
    "route":          "/route",
}


def find_api_key() -> str | None:
    """Busca el CommAPIKey.txt en todas las rutas conocidas."""
    for p in KEY_PATHS:
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return None


def get_key_path() -> Path | None:
    for p in KEY_PATHS:
        if p.exists():
            return p
    return None


def tsw_get(endpoint: str, key: str) -> dict | None:
    """Hace GET a un endpoint de TSW con la key de autenticación."""
    try:
        r = requests.get(
            f"{TSW_API}{endpoint}",
            headers={"X-API-Key": key},
            timeout=2,
        )
        if r.status_code == 200:
            return r.json()
        return None
    except requests.exceptions.ConnectionError:
        return None
    except Exception:
        return None


def color(text: str, c: str) -> str:
    return f"{c}{text}{Style.RESET_ALL}" if COLOR else text


def fmt_speed(mps: float) -> str:
    """Convierte m/s a km/h."""
    kmh = mps * 3.6
    if kmh > 0:
        return color(f"{kmh:5.1f} km/h", Fore.GREEN)
    return color(f"{kmh:5.1f} km/h", Fore.WHITE)


def print_dashboard(data: dict):
    """Imprime el dashboard en consola."""
    os.system("cls" if sys.platform == "win32" else "clear")

    print(color("═" * 60, Fore.CYAN))
    print(color("  🚂  TSW6 MONITOR  —  " + datetime.now().strftime("%H:%M:%S"), Fore.CYAN + Style.BRIGHT))
    print(color("═" * 60, Fore.CYAN))

    # INFO DEL JUEGO
    info = data.get("info")
    if info:
        print(f"\n{color('JUEGO', Fore.YELLOW + Style.BRIGHT)}")
        print(f"  Versión  : {info.get('version', '?')}")
        print(f"  Estado   : {info.get('gameState', '?')}")
        print(f"  Modo     : {info.get('gameMode', '?')}")

    # RUN INFO (ruta activa)
    run = data.get("run_info")
    if run:
        print(f"\n{color('RECORRIDO ACTIVO', Fore.YELLOW + Style.BRIGHT)}")
        print(f"  Ruta     : {run.get('routeName', '?')}")
        print(f"  Servicio : {run.get('serviceName', '?')}")
        sim_time = run.get("simulationTime", 0)
        h = int(sim_time // 3600)
        m = int((sim_time % 3600) // 60)
        print(f"  Hora sim : {h:02d}:{m:02d}")

    # VEHÍCULO / TELEMETRÍA
    vehicles = data.get("vehicles")
    if vehicles and isinstance(vehicles, list) and len(vehicles) > 0:
        v = vehicles[0]
        print(f"\n{color('TREN', Fore.YELLOW + Style.BRIGHT)}")
        print(f"  Vehículo : {v.get('name', '?')}")
        
        speed = v.get("speed", 0)
        speed_limit = v.get("speedLimit", 0)
        print(f"  Velocidad: {fmt_speed(speed)}", end="")
        if speed_limit > 0:
            pct = speed / speed_limit * 100
            if pct > 100:
                print(f"  {color('⚠ EXCESO', Fore.RED + Style.BRIGHT)}", end="")
        print()

        if speed_limit > 0:
            print(f"  Límite   : {fmt_speed(speed_limit)}")
        
        throttle = v.get("throttle", v.get("notch", None))
        if throttle is not None:
            filled = max(0, min(int(throttle * 20), 20))
            bar = "█" * filled + "░" * (20 - filled)
            print(f"  Tracción : [{color(bar, Fore.GREEN)}] {throttle*100:.0f}%")

        brake = v.get("brake", v.get("brakeValue", None))
        if brake is not None:
            filled = max(0, min(int(brake * 20), 20))
            bar = "█" * filled + "░" * (20 - filled)
            print(f"  Freno    : [{color(bar, Fore.RED)}] {brake*100:.0f}%")

        # Puertas
        doors_l = v.get("doorsLeft", None)
        doors_r = v.get("doorsRight", None)
        if doors_l is not None or doors_r is not None:
            dl = color("ABIERTA", Fore.RED) if doors_l else color("cerrada", Fore.GREEN)
            dr = color("ABIERTA", Fore.RED) if doors_r else color("cerrada", Fore.GREEN)
            print(f"  Puertas  : Izq={dl}  Der={dr}")

    # SPEEDS MOSTRADAS (ETCS)
    speeds = data.get("displayed")
    if speeds:
        print(f"\n{color('ETCS', Fore.YELLOW + Style.BRIGHT)}")
        current = speeds.get("currentSpeed", speeds.get("speed", None))
        target = speeds.get("targetSpeed", speeds.get("permittedSpeed", None))
        if current is not None:
            print(f"  Vel.actual: {fmt_speed(current)}")
        if target is not None:
            print(f"  Vel.permit: {fmt_speed(target)}")

    print(f"\n{color('─' * 60, Fore.CYAN)}")
    print(color("  Ctrl+C para salir  |  Auto-refresh cada 1s", Fore.WHITE))


def discover_endpoints(key: str):
    """Descubre qué endpoints están disponibles y muestra su estructura."""
    print(color("\n🔍 Explorando endpoints disponibles...\n", Fore.CYAN))
    results = {}
    for name, path in ENDPOINTS.items():
        data = tsw_get(path, key)
        status = color("✓ OK", Fore.GREEN) if data is not None else color("✗ N/A", Fore.RED)
        print(f"  {path:25s}  {status}")
        if data is not None:
            results[name] = data
    print()
    return results


def monitor_loop(key: str, key_path: Path, interval: float = 1.0):
    """Bucle principal de monitorización en tiempo real."""
    last_key_mtime = key_path.stat().st_mtime
    
    print(color("\n▶ Iniciando monitor... (Ctrl+C para salir)\n", Fore.GREEN))
    time.sleep(1)

    try:
        while True:
            # Si TSW se reinició, la key cambia — recargarla automáticamente
            current_mtime = key_path.stat().st_mtime
            if current_mtime != last_key_mtime:
                key = key_path.read_text(encoding="utf-8").strip()
                last_key_mtime = current_mtime
                print(color("  🔑 API key actualizada automáticamente", Fore.YELLOW))

            # Recopilar todos los datos
            data = {}
            for name, path in ENDPOINTS.items():
                result = tsw_get(path, key)
                if result is not None:
                    data[name] = result

            if not data:
                os.system("cls" if sys.platform == "win32" else "clear")
                print(color("\n  ⏳ Esperando a que TSW6 esté disponible...", Fore.YELLOW))
                print(color("  Asegúrate de:", Fore.WHITE))
                print("    1. TSW6 corriendo con -HTTPAPI en los argumentos de Steam")
                print("    2. Haber cargado un escenario (no en el menú principal)")
            else:
                print_dashboard(data)

            time.sleep(interval)

    except KeyboardInterrupt:
        print(color("\n\nMonitor detenido.\n", Fore.YELLOW))


def save_snapshot(key: str, filename: str = "tsw_snapshot.json"):
    """Guarda una captura de todos los datos en un fichero JSON."""
    data = {}
    for name, path in ENDPOINTS.items():
        result = tsw_get(path, key)
        if result is not None:
            data[name] = result
    data["timestamp"] = datetime.now().isoformat()
    
    out = Path(__file__).parent / filename
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(color(f"\n✓ Snapshot guardado en: {out}\n", Fore.GREEN))
    return data


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print(color("\n" + "═" * 60, Fore.CYAN))
    print(color("  TSW6 API MONITOR  |  github.com/campinge/railbridge", Fore.CYAN))
    print(color("═" * 60 + "\n", Fore.CYAN))

    # 1. Buscar API key
    key = find_api_key()
    key_path = get_key_path()
    if not key or key_path is None:
        print(color("  ✗ No se encontró CommAPIKey.txt", Fore.RED))
        print("  Inicia TSW6 con -HTTPAPI al menos una vez para generarla.")
        sys.exit(1)
    
    print(color(f"  ✓ Key encontrada en: {key_path}", Fore.GREEN))
    print(color(f"  ✓ Key: {key[:10]}...{key[-5:]}", Fore.GREEN))

    # 2. Modo según argumento
    modo = sys.argv[1] if len(sys.argv) > 1 else "monitor"

    if modo == "discover":
        # Ver qué endpoints responden y qué devuelven
        datos = discover_endpoints(key)
        if datos:
            print(color("Datos de muestra del primer endpoint disponible:\n", Fore.CYAN))
            primero = next(iter(datos.values()))
            print(json.dumps(primero, indent=2, ensure_ascii=False)[:2000])

    elif modo == "snapshot":
        # Guardar captura JSON
        save_snapshot(key)

    elif modo == "raw":
        # Imprimir JSON crudo en continuo
        try:
            while True:
                for name, path in ENDPOINTS.items():
                    d = tsw_get(path, key)
                    if d:
                        print(f"\n── {name} ──")
                        print(json.dumps(d, indent=2, ensure_ascii=False))
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    else:
        # Modo por defecto: dashboard visual
        monitor_loop(key, key_path, interval=1.0)
