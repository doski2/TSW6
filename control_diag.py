#!/usr/bin/env python3
"""
control_diag.py — Fase 0: diagnóstico de mandos (FREIGHT NA)

Muestra en vivo los valores que envía RailBridge Companion para cada mando
del tren. Sirve para documentar rangos reales antes de implementar el learner
multi-eje (SD40-2, etc.).

Uso:
  python control_diag.py
  python control_diag.py --save   # guarda resumen en logs/control_diag_*.txt

Instrucciones en sesión:
  1. Arranca TSW6 + RailBridge CMP
  2. Sube al SD40-2 (u otro tren NA)
  3. Mueve UN mando a la vez y observa qué campo cambia
  4. Ctrl+C al terminar → resumen min/max y campos API detectados
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from typing import Any, Optional

from tsw_connection import TswConnection

# Mandos principales (mapeo telem → etiqueta humana)
_PRIMARY = (
    ("throttle",          "Tracción (muescas 0–8)"),
    ("train_brake_pct",   "Freno automático (% o presión)"),
    ("train_brake_phase", "Fase freno automático"),
    ("ind_brake_pct",     "Freno independiente (%)"),
    ("ind_brake_phase",   "Fase freno independiente"),
    ("dyn_brake",         "Freno dinámico (muescas)"),
)

# Fallback legacy (handles planos si la API los envía)
_LEGACY_BRAKE = (
    ("train_brake", "Freno auto (handle plano)"),
    ("ind_brake",   "Freno ind (handle plano)"),
)

# API key esperada en raw_controls (para cruzar nombres)
_API_HINTS = {
    "throttle":          "throttle_notch",
    "train_brake_pct":   "train_brake_handle.handle_position",
    "train_brake_phase": "train_brake_handle.label / status",
    "ind_brake_pct":     "locomotive_brake_handle.handle_position",
    "ind_brake_phase":   "locomotive_brake_handle.label / status",
    "dyn_brake":         "electric_brake_handle.handle_position",
}

_META_SUFFIXES = (".confidence", ".provenance", ".source")


def _is_meta_api_key(key: str) -> bool:
    return any(key.endswith(s) for s in _META_SUFFIXES)


def _enable_utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _fmt_val(v: Any) -> str:
    if v is None:
        return "?"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


class SessionStats:
    """Min/max y historial de cambios por campo."""

    def __init__(self) -> None:
        self.minmax: dict[str, tuple[Any, Any]] = {}
        self.changes: list[str] = []
        self._last: dict[str, Any] = {}
        self.seen_api_keys: set[str] = set()

    def update(self, snap: dict, raw: dict) -> list[str]:
        """Registra muestra; devuelve líneas de cambios en este ciclo."""
        self.seen_api_keys.update(raw.keys())
        lines: list[str] = []
        now = time.strftime("%H:%M:%S")

        for key, _label in _PRIMARY:
            val = snap.get(key)
            self._track(key, val)
            if key in self._last and self._last[key] != val and val is not None:
                lines.append(
                    f"  [{now}] {key}: {_fmt_val(self._last[key])} → {_fmt_val(val)}")
            if val is not None:
                self._last[key] = val

        for key, _label in _LEGACY_BRAKE:
            val = snap.get(key)
            if val is None:
                continue
            self._track(key, val)
            if key in self._last and self._last[key] != val:
                lines.append(
                    f"  [{now}] {key}: {_fmt_val(self._last[key])} → {_fmt_val(val)}")
            self._last[key] = val

        # Campos API adicionales no mapeados
        for api_key, val in raw.items():
            if _is_meta_api_key(api_key):
                continue
            if api_key in ("throttle_notch", "power_display", "throttle_status",
                           "reverser_notch", "traction_lock"):
                continue
            sk = f"api:{api_key}"
            self._track(sk, val)
            if sk in self._last and self._last[sk] != val:
                lines.append(
                    f"  [{now}] {api_key}: {_fmt_val(self._last[sk])} → {_fmt_val(val)}")
            self._last[sk] = val

        self.changes.extend(lines)
        return lines

    def _track(self, key: str, val: Any) -> None:
        if val is None:
            return
        if key not in self.minmax:
            self.minmax[key] = (val, val)
        else:
            lo, hi = self.minmax[key]
            try:
                if val < lo:
                    lo = val
                if val > hi:
                    hi = val
            except TypeError:
                pass
            self.minmax[key] = (lo, hi)


def _render(snap: dict, stats: SessionStats, recent: list[str],
            samples: int, vehicle: Optional[str]) -> None:
    _clear()
    veh = vehicle or "?"
    print("═" * 72)
    print("  DIAGNÓSTICO DE MANDOS — Fase 0 (FREIGHT NA)")
    print(f"  Tren: {veh}   ·   muestras: {samples}")
    print("═" * 72)
    print()
    print("  Mueve UN mando a la vez en el juego y observa qué valor cambia.")
    print("  Teclas NA (tsw-en): tracción A/D · train ';/ · ind [/] · dyn ,/.")
    print("  NA freight: train/ind = % + fase · dyn = muescas (buscar brake_gauges.*)")
    print()
    print("  ── Mandos principales ──────────────────────────────────────────")
    for key, label in _PRIMARY:
        val = snap.get(key)
        api = _API_HINTS.get(key, "")
        mm = stats.minmax.get(key)
        mm_str = (f"  [visto {mm[0]} … {mm[1]}]" if mm else "  [sin datos aún]")
        print(f"  {label}")
        print(f"    valor={_fmt_val(val):>8}   API: {api}{mm_str}")

    raw = snap.get("raw_controls") or {}
    brake_keys = [k for k in sorted(raw.keys())
                  if "brake" in k.lower() and not _is_meta_api_key(k)]
    other = [k for k in sorted(raw.keys())
             if "brake" not in k.lower()
             and not _is_meta_api_key(k)
             and k not in ("throttle_notch", "power_display", "throttle_status",
                           "reverser_notch", "ammeter", "traction_lock")]
    if brake_keys:
        print()
        print("  ── Campos API de frenos (brake_gauges / status) ───────────────")
        for k in brake_keys:
            print(f"    {k} = {_fmt_val(raw[k])}")
    if other:
        print()
        print("  ── Otros campos API en controls ───────────────────────────────")
        for k in other:
            print(f"    {k} = {_fmt_val(raw[k])}")

    print()
    print("  ── Telemetría ─────────────────────────────────────────────────")
    print(f"    velocidad = {_fmt_val(snap.get('speed_mph'))} mph   "
          f"límite = {_fmt_val(snap.get('limit_mph'))} mph")
    print(f"    gradiente = {_fmt_val(snap.get('gradient_pct'))}%   "
          f"acel = {_fmt_val(snap.get('accel_mps2'))} m/s²")

    if recent:
        print()
        print("  ── Últimos cambios ────────────────────────────────────────────")
        for line in recent[-6:]:
            print(line)

    print()
    print("  Ctrl+C para terminar y ver resumen (min/max por mando)")
    print("═" * 72)


def _write_summary(path: str, stats: SessionStats, vehicle: Optional[str]) -> None:
    lines = [
        "DIAGNÓSTICO DE MANDOS — Fase 0",
        f"Fecha: {datetime.now().isoformat(timespec='seconds')}",
        f"Tren: {vehicle or '?'}",
        "",
        "── Min / Max observados ──",
    ]
    for key, label in _PRIMARY:
        mm = stats.minmax.get(key)
        if mm:
            lines.append(f"  {label}: min={mm[0]}  max={mm[1]}")
        else:
            lines.append(f"  {label}: (sin datos)")

    lines.append("")
    lines.append("── Campos API con 'brake' en el nombre ──")
    brake_seen = [k for k in sorted(stats.seen_api_keys)
                  if "brake" in k.lower() and not _is_meta_api_key(k)]
    if brake_seen:
        for k in brake_seen:
            sk = f"api:{k}"
            mm = stats.minmax.get(sk)
            if mm:
                lines.append(f"  {k}: min={mm[0]}  max={mm[1]}")
            else:
                lines.append(f"  {k}: (presente, sin rango)")
    else:
        lines.append("  (ninguno — mover frenos y repetir sesión)")

    lines.append("")
    lines.append("── Otros campos API en controls ──")
    for k in sorted(stats.seen_api_keys):
        if "brake" in k.lower() or _is_meta_api_key(k):
            continue
        sk = f"api:{k}"
        mm = stats.minmax.get(sk)
        if mm:
            lines.append(f"  {k}: min={mm[0]}  max={mm[1]}")
        else:
            lines.append(f"  {k}: (presente, sin rango)")

    if stats.changes:
        lines.append("")
        lines.append("── Historial de cambios ──")
        lines.extend(stats.changes)

    lines.append("")
    lines.append("── Rellenar en FREIGHT_NA_PLAN.md → Resultados Fase 0 ──")
    rows = (
        ("Tracción", "throttle_notch", "throttle"),
        ("Freno auto %", "train_brake_handle.handle_position", "train_brake_pct"),
        ("Fase freno auto", "train_brake_handle.label", "train_brake_phase"),
        ("Freno ind %", "locomotive_brake_handle.handle_position", "ind_brake_pct"),
        ("Fase freno ind", "locomotive_brake_handle.label", "ind_brake_phase"),
        ("Freno dinámico", "electric_brake_handle.handle_position", "dyn_brake"),
    )
    for label, api, snap_key in rows:
        mm = stats.minmax.get(snap_key)
        if mm:
            lines.append(f"| {label} | `{api}` | {mm[0]} | {mm[1]} | |")
        else:
            lines.append(f"| {label} | `{api}` | ? | ? | |")

    text = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\nResumen guardado en: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnóstico de mandos RailBridge — Fase 0 FREIGHT NA")
    parser.add_argument("--save", action="store_true",
                        help="Guardar resumen en logs/ al salir (siempre recomendado)")
    args = parser.parse_args()

    _enable_utf8()

    conn = TswConnection()
    print("Buscando RailBridge Companion…")
    for _ in range(30):
        conn.probe()
        if conn.mode == "companion":
            break
        time.sleep(1.0)

    if conn.mode != "companion":
        print("ERROR: No se pudo conectar al Companion (¿CMP activo en RailBridge?)")
        sys.exit(1)

    print(f"Conectado. Iniciando diagnóstico en 2 s…")
    time.sleep(2.0)

    stats = SessionStats()
    samples = 0
    recent: list[str] = []

    try:
        while True:
            snap = conn.get_controls_snapshot()
            raw = snap.get("raw_controls") or {}
            new_changes = stats.update(snap, raw)
            if new_changes:
                recent = (recent + new_changes)[-20:]
            samples += 1

            if samples == 1 or samples % 3 == 0:  # ~0.6 s entre refrescos
                _render(snap, stats, recent, samples, snap.get("vehicle"))

            time.sleep(0.2)
    except KeyboardInterrupt:
        pass

    _clear()
    print("═" * 72)
    print("  RESUMEN FASE 0")
    print("═" * 72)
    vehicle = conn.get_vehicle_name()
    print(f"  Tren: {vehicle or '?'}")
    print()
    for key, label in _PRIMARY:
        mm = stats.minmax.get(key)
        if mm:
            print(f"  {label}")
            print(f"    min = {mm[0]}   max = {mm[1]}")
        else:
            print(f"  {label}")
            print("    (no se recibió ningún valor — ¿moviste ese mando?)")

    if stats.seen_api_keys:
        print()
        print("  Campos API detectados:", ", ".join(sorted(stats.seen_api_keys)))
    else:
        print()
        print("  AVISO: no llegó ningún campo en controls.*")
        print("  ¿Estás en cabina con el tren encendido y CMP activo?")

    print()
    print("  Copia los min/max a FREIGHT_NA_PLAN.md → sección Resultados Fase 0")
    print("═" * 72)

    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = (vehicle or "desconocido").replace(" ", "_")[:40]
    path = os.path.join(log_dir, f"control_diag_{slug}_{stamp}.txt")
    _write_summary(path, stats, vehicle)


if __name__ == "__main__":
    main()
