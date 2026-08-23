#!/usr/bin/env python3
"""
Lee telemetría escrita por TelemetryProbeMod (UE4SS) en %TEMP%\\TSW6Bridge\\GetData.txt.

Uso:
  python tsw_ue4ss_reader.py
  python tsw_ue4ss_reader.py --log
  python tsw_ue4ss_reader.py --benchmark 30
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

if os.name == "nt":
    try:
        import ctypes

        _CONSOLE_HANDLE = ctypes.windll.kernel32.GetStdHandle(-11)
        _CONSOLE_MODE = ctypes.c_uint32()
        ctypes.windll.kernel32.GetConsoleMode(_CONSOLE_HANDLE, ctypes.byref(_CONSOLE_MODE))
        ctypes.windll.kernel32.SetConsoleMode(
            _CONSOLE_HANDLE, _CONSOLE_MODE.value | 0x0004
        )
    except Exception:
        pass
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from tsw6.telemetry.driver_aid_parser import parse_driver_aid_planning
from tsw6.governor.governor_constants import NOTCH_LABELS

try:
    from colorama import Fore, Style, init  # type: ignore[assignment]

    init(autoreset=True)
    _COLOR = True
except ImportError:
    _COLOR = False

    class Fore:
        GREEN = CYAN = YELLOW = WHITE = RED = MAGENTA = ""

    class Style:
        BRIGHT = RESET_ALL = ""


def power_to_combined_notch(
    power: Optional[float], power_neg: bool = False
) -> Optional[int]:
    """HUD Power (signed) → muesca combinada 0–8 del Class 323."""
    if power is None:
        return None
    p = float(power)
    if power_neg:
        p = -abs(p)
    return max(0, min(8, 4 + round(p)))


def default_getdata_path() -> Path:
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    return Path(temp) / "TSW6Bridge" / "GetData.txt"


def parse_probe_line(line: str) -> dict[str, Any]:
    """Parsea una línea `key=value` separada por espacios."""
    out: dict[str, Any] = {}
    for token in line.strip().split():
        if "=" not in token:
            continue
        key, _, raw = token.partition("=")
        if raw == "?":
            out[key] = "?" if key == "vehicle" else None
            continue
        if key in ("seq", "handle_notch"):
            try:
                out[key] = int(raw)
            except ValueError:
                out[key] = raw
            continue
        if key in ("power_neg", "doors_open", "doors_telem", "doors_dmi"):
            out[key] = raw in ("1", "true", "True")
            continue
        if key == "vehicle":
            out[key] = raw
            continue
        try:
            out[key] = float(raw)
        except ValueError:
            out[key] = raw
    return out


@dataclass
class ProbeSnapshot:
    seq: Optional[int] = None
    speed_ms: Optional[float] = None
    power: Optional[float] = None
    power_neg: bool = False
    handle_notch: Optional[int] = None
    train_brake: Optional[float] = None
    loco_brake: Optional[float] = None
    dyn_brake: Optional[float] = None
    accel_ms2: Optional[float] = None
    max_speed_ms: Optional[float] = None
    speed_limit_ms: Optional[float] = None
    gradient_pct: Optional[float] = None
    dist_limit_cm: Optional[float] = None
    next_limit_ms: Optional[float] = None
    dist_limit2_cm: Optional[float] = None
    next_limit2_ms: Optional[float] = None
    odo_m: Optional[float] = None
    doors_open: Optional[bool] = None
    doors_telem: Optional[bool] = None
    doors_dmi: Optional[bool] = None
    vehicle: str = "?"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProbeSnapshot":
        return cls(
            seq=data.get("seq"),
            speed_ms=data.get("speed_ms"),
            power=data.get("power"),
            power_neg=bool(data.get("power_neg", False)),
            handle_notch=data.get("handle_notch"),
            train_brake=data.get("train_brake"),
            loco_brake=data.get("loco_brake"),
            dyn_brake=data.get("dyn_brake"),
            accel_ms2=data.get("accel_ms2"),
            max_speed_ms=data.get("max_speed_ms"),
            speed_limit_ms=data.get("speed_limit_ms"),
            gradient_pct=data.get("gradient_pct"),
            dist_limit_cm=data.get("dist_limit_cm"),
            next_limit_ms=data.get("next_limit_ms"),
            dist_limit2_cm=data.get("dist_limit2_cm"),
            next_limit2_ms=data.get("next_limit2_ms"),
            odo_m=data.get("odo_m"),
            doors_open=data.get("doors_open"),
            doors_telem=data.get("doors_telem", data.get("doors_open")),
            doors_dmi=data.get("doors_dmi"),
            vehicle=str(data.get("vehicle") or "?"),
        )

    def has_limit_planning(self) -> bool:
        return self.dist_limit_cm is not None and self.next_limit_ms is not None

    def planning_dict(self) -> dict[str, Any]:
        """Planning P1 desde campos probe (reutiliza driver_aid_parser)."""
        if not self.has_limit_planning():
            return {}
        data: dict[str, Any] = {
            "distanceToNextSpeedLimit": self.dist_limit_cm,
            "nextSpeedLimit": {"value": self.next_limit_ms},
        }
        if self.dist_limit2_cm is not None and self.next_limit2_ms is not None:
            data["nextSpeedLimits"] = [{
                "distanceToNextSpeedLimit": self.dist_limit2_cm,
                "value": {"value": self.next_limit2_ms},
            }]
        return parse_driver_aid_planning(data)

    def to_telemetry_dict(self) -> dict[str, Any]:
        """Dict aproximado al de tsw_monitor / get_telemetry."""
        mph = self.speed_ms * 2.236936 if self.speed_ms is not None else None
        limit_mph = (
            self.speed_limit_ms * 2.236936
            if self.speed_limit_ms is not None
            else None
        )
        return {
            "speed_mph": mph,
            "speed_ms": self.speed_ms,
            "limit_mph": limit_mph,
            "accel_mps2": self.accel_ms2,
            "vehicle_name": self.vehicle,
            "handle_notch": self.combined_handle_notch(),
            "power": self.power,
            "power_negative": self.power_neg,
            "train_brake": self.train_brake,
            "loco_brake": self.loco_brake,
            "dyn_brake": self.dyn_brake,
            "max_speed_ms": self.max_speed_ms,
            "gradient_pct": self.gradient_pct,
            "source": "ue4ss",
            "seq": self.seq,
        }

    def combined_handle_notch(self) -> Optional[int]:
        if self.handle_notch is not None:
            return int(self.handle_notch)
        return power_to_combined_notch(self.power, self.power_neg)


def read_probe_raw_line(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    return text.splitlines()[-1].strip()


def read_probe_file(path: Path) -> Optional[ProbeSnapshot]:
    line = read_probe_raw_line(path)
    if not line:
        return None
    return ProbeSnapshot.from_dict(parse_probe_line(line))


from tsw6.paths import LOGS_DIR


def default_log_path() -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOGS_DIR / f"ue4ss_probe_{stamp}.txt"


class SessionLogger:
    """Escribe CSV + línea cruda GetData.txt para compartir sesiones de diagnóstico."""

    _CSV_HEADER = (
        "time_s,seq,hz,speed_mph,limit_mph,max_mph,handle_notch,power,"
        "train_brake,loco_brake,dyn_brake,accel_ms2,gradient_pct,vehicle"
    )

    def __init__(self, path: Path, getdata_path: Path) -> None:
        self.path = path
        self.getdata_path = getdata_path
        self._t0 = time.perf_counter()
        self._samples = 0
        self._first_seq: Optional[int] = None
        self._last_seq: Optional[int] = None
        self._hz_sum = 0.0
        self._hz_n = 0
        self._f = path.open("w", encoding="utf-8", newline="\n")
        self._write_header()

    def _write_header(self) -> None:
        self._f.write("# UE4SS probe — log de sesión\n")
        self._f.write(f"# inicio: {datetime.now().isoformat(timespec='seconds')}\n")
        self._f.write(f"# getdata: {self.getdata_path}\n")
        self._f.write("# Mueve el mando (A/D) unos segundos. Ctrl+C para cerrar.\n")
        self._f.write(f"#\n{self._CSV_HEADER}\n")
        self._f.flush()

    def log_sample(
        self,
        snap: ProbeSnapshot,
        hz: Optional[float],
        raw_line: Optional[str],
    ) -> None:
        self._samples += 1
        if snap.seq is not None:
            if self._first_seq is None:
                self._first_seq = snap.seq
            self._last_seq = snap.seq
        if hz is not None:
            self._hz_sum += hz
            self._hz_n += 1

        mph = snap.speed_ms * 2.236936 if snap.speed_ms is not None else ""
        lim = snap.speed_limit_ms * 2.236936 if snap.speed_limit_ms is not None else ""
        mx = snap.max_speed_ms * 2.236936 if snap.max_speed_ms else ""
        notch = snap.combined_handle_notch()
        row = [
            f"{time.perf_counter() - self._t0:.3f}",
            str(snap.seq or ""),
            f"{hz:.2f}" if hz is not None else "",
            f"{mph:.2f}" if mph != "" else "",
            f"{lim:.2f}" if lim != "" else "",
            f"{mx:.2f}" if mx != "" else "",
            str(notch if notch is not None else ""),
            str(snap.power if snap.power is not None else ""),
            str(snap.train_brake if snap.train_brake is not None else ""),
            str(snap.loco_brake if snap.loco_brake is not None else ""),
            str(snap.dyn_brake if snap.dyn_brake is not None else ""),
            str(snap.accel_ms2 if snap.accel_ms2 is not None else ""),
            str(snap.gradient_pct if snap.gradient_pct is not None else ""),
            snap.vehicle,
        ]
        self._f.write(",".join(row) + "\n")
        if raw_line:
            self._f.write(f"# raw: {raw_line}\n")
        self._f.flush()

    def close(self) -> None:
        elapsed = time.perf_counter() - self._t0
        avg_hz = self._hz_sum / self._hz_n if self._hz_n else 0.0
        self._f.write("#\n")
        self._f.write(f"# fin: {datetime.now().isoformat(timespec='seconds')}\n")
        self._f.write(f"# duracion_s: {elapsed:.1f}\n")
        self._f.write(f"# muestras: {self._samples}\n")
        self._f.write(f"# seq: {self._first_seq} .. {self._last_seq}\n")
        self._f.write(f"# hz_medio: {avg_hz:.1f}\n")
        self._f.close()


def _c(text: str, color: str) -> str:
    return f"{color}{text}{Style.RESET_ALL}" if _COLOR else text


def _fmt_mph(mps: Optional[float]) -> str:
    if mps is None:
        return "?"
    mph = mps * 2.236936
    return f"{mph:6.1f} mph"


def _clear_screen() -> None:
    # No usar os.system("cls") — en Windows abre miles de ventanas cmd.exe.
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _home_screen() -> None:
    """Cursor al inicio sin borrar pantalla (evita parpadeo a ~20 Hz)."""
    sys.stdout.write("\033[H")
    sys.stdout.flush()


# Refresco visual máximo (~8 Hz); la lectura/log sigue a interval del probe.
_DISPLAY_MIN_S = 0.12


def fetch_api_gradient() -> Optional[float]:
    """DriverAid.Data.gradient vía HTTPAPI (referencia para validar probe)."""
    try:
        from tsw6.telemetry.tsw_api_client import client_from_key_file
        from tsw6.telemetry.tsw_telemetry_source import _parse_gradient_pct
    except ImportError:
        return None
    client = client_from_key_file()
    if client is None or not client.probe():
        return None
    node = client.get_node("DriverAid.Data")
    return _parse_gradient_pct(node)


def render_snapshot(
    snap: ProbeSnapshot,
    hz: Optional[float],
    path: Path,
    api_grad: Optional[float] = None,
) -> str:
    hz_str = f"{hz:5.1f} Hz" if hz is not None else "  ? Hz"
    notch = snap.combined_handle_notch()
    notch_str = "?"
    if notch is not None:
        notch_str = f"{notch} {NOTCH_LABELS.get(notch, '')}"
    max_mph = _fmt_mph(snap.max_speed_ms) if snap.max_speed_ms else "?"
    grad_probe = (
        "?"
        if snap.gradient_pct is None
        else f"{snap.gradient_pct:+.3f}"
    )
    if api_grad is not None:
        grad_line = f"  grad: probe {grad_probe} %   api {_c(f'{api_grad:+.3f}', Fore.MAGENTA)} %"
    else:
        grad_line = f"  grad: {grad_probe} %"
    lines = [
        f"  UE4SS probe  {_c(hz_str, Fore.GREEN)}  seq={snap.seq or '?'}",
        f"  archivo: {path}",
        f"  tren: {snap.vehicle}",
        f"  vel:  {_c(_fmt_mph(snap.speed_ms), Fore.CYAN)}"
        f"   lim: {_fmt_mph(snap.speed_limit_ms)}"
        f"   max: {max_mph}",
        f"  acel: {snap.accel_ms2 if snap.accel_ms2 is not None else '?':>8} m/s²",
        grad_line,
        f"  muesca: {_c(notch_str, Fore.YELLOW)}"
        f"   (power={snap.power if snap.power is not None else '?'}"
        f"  train={snap.train_brake if snap.train_brake is not None else '?'})",
    ]
    return "\n".join(lines)


def benchmark(path: Path, seconds: float) -> dict[str, float | int | str | bool]:
    deadline = time.perf_counter() + seconds
    last_seq: Optional[int] = None
    updates = 0
    t0 = time.perf_counter()
    last_progress = -1
    interrupted = False
    print(f"Midiendo {seconds:.0f}s en {path} (Ctrl+C = parar antes)...")
    try:
        while time.perf_counter() < deadline:
            snap = read_probe_file(path)
            if snap and snap.seq is not None and snap.seq != last_seq:
                updates += 1
                last_seq = snap.seq
            elapsed = time.perf_counter() - t0
            sec_done = int(elapsed)
            if sec_done != last_progress:
                print(
                    f"  {sec_done}/{int(seconds)}s  {updates} actualizaciones\r",
                    end="",
                    flush=True,
                )
                last_progress = sec_done
            time.sleep(0.005)
    except KeyboardInterrupt:
        interrupted = True
    elapsed = max(time.perf_counter() - t0, 1e-6)
    print()
    return {
        "updates": updates,
        "seconds": elapsed,
        "hz": updates / elapsed,
        "last_seq": last_seq or -1,
        "interrupted": interrupted,
    }


def monitor_loop(
    path: Path,
    interval: float,
    logger: Optional[SessionLogger] = None,
    with_api: bool = False,
) -> None:
    last_seq: Optional[int] = None
    last_change = time.perf_counter()
    last_render = 0.0
    hz: Optional[float] = None
    rendered = False
    stale_reads = 0
    stale_warned = False
    api_grad: Optional[float] = None
    last_api_poll = 0.0

    print(f"Buscando {path}")
    if with_api:
        print("Modo --api: compara probe vs DriverAid.Data (requiere -HTTPAPI)")
    if logger:
        print(f"Log: {logger.path}")
    print("Arranca TSW6, carga escenario, sube a cabina. F7 toggle probe. Ctrl+C salir.\n")

    while True:
        snap = read_probe_file(path)
        raw_line = read_probe_raw_line(path) if logger else None
        now = time.perf_counter()
        if with_api and now - last_api_poll >= 1.0:
            api_grad = fetch_api_gradient()
            last_api_poll = now
        if snap and snap.seq is not None and snap.seq != last_seq:
            dt = now - last_change
            if dt >= 0.01:
                instant = 1.0 / dt
                # Media móvil: el Hz instantáneo salta (9↔19) por jitter de lectura.
                hz = instant if hz is None else 0.25 * instant + 0.75 * hz
            last_seq = snap.seq
            last_change = now
            stale_reads = 0
            stale_warned = False
            if logger:
                logger.log_sample(snap, hz, raw_line)
            if now - last_render >= _DISPLAY_MIN_S:
                if rendered:
                    _home_screen()
                else:
                    _clear_screen()
                    rendered = True
                print(render_snapshot(snap, hz, path, api_grad))
                sys.stdout.write("\033[J")
                sys.stdout.flush()
                last_render = now
        elif snap is not None and snap.seq == last_seq:
            stale_reads += 1
            # Leer el mismo seq dos veces es normal (~50 ms entre lectura y escritura).
            # Avisar solo si lleva ~2 s sin seq nuevo (probe pausado / menú / fuera de cabina).
            if stale_reads >= 40 and not stale_warned:
                stale_warned = True
                print(
                    f"\n  (sin datos nuevos ~2s — seq={last_seq}; "
                    f"¿menú, pausa o F7 apagado?)"
                )
        elif snap is None:
            print(f"Esperando {path} ...", end="\r", flush=True)
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor telemetría UE4SS TelemetryProbeMod")
    parser.add_argument(
        "--path",
        type=Path,
        default=default_getdata_path(),
        help="Ruta a GetData.txt (default: %%TEMP%%\\TSW6Bridge\\GetData.txt)",
    )
    parser.add_argument("--interval", type=float, default=0.05, help="Periodo de lectura (s)")
    parser.add_argument(
        "--log",
        nargs="?",
        const="",
        metavar="ARCHIVO",
        help="Guardar sesión en logs/ue4ss_probe_<fecha>.txt (o ruta indicada)",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Comparar gradient_pct probe vs DriverAid.Data (TSW con -HTTPAPI)",
    )
    parser.add_argument(
        "--benchmark",
        type=float,
        metavar="SEG",
        help="Medir Hz del probe durante N segundos y salir",
    )
    args = parser.parse_args()

    log_path: Optional[Path] = None
    if args.log is not None:
        log_path = Path(args.log) if args.log else default_log_path()

    if args.benchmark:
        stats = benchmark(args.path, args.benchmark)
        note = " (interrumpido)" if stats.get("interrupted") else ""
        print(
            f"UE4SS probe{note}: {stats['updates']} actualizaciones en "
            f"{stats['seconds']:.1f}s -> {stats['hz']:.1f} Hz "
            f"(last seq={stats['last_seq']})"
        )
        return

    logger: Optional[SessionLogger] = None
    if log_path is not None:
        logger = SessionLogger(log_path, args.path)

    try:
        monitor_loop(args.path, args.interval, logger, with_api=args.api)
    except KeyboardInterrupt:
        print("\nSalida.")
    finally:
        if logger:
            logger.close()
            print(f"Log guardado: {logger.path}")


if __name__ == "__main__":
    main()
