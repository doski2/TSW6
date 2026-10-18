"""OCR de la distancia al marcador de parada del HUD de TSW6 — solo medición.

El HUD del juego muestra, bajo el icono de la mano, la distancia al punto de parada
(``1.465 ft (pies)``). ``DriverAid.TrackData`` entrega otra cosa (fin de andén, no el tablón),
así que este módulo lee el número del HUD para **medir** el desfase de la app y evaluar con
``hud_ocr_eval`` si corregir la distancia cada N capturas compensaría. No entra en el frenado:
el resultado solo se escribe en el JSONL de la sesión (``hud_ocr_m``).

Dependencias opcionales: ``mss``, ``Pillow``, ``pytesseract`` y el binario Tesseract
(ver ``requirements-ocr.txt`` y ``docs/v2/HUD_OCR_MEDICION.md``).
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

FT_TO_M = 0.3048
YD_TO_M = 0.9144
MI_TO_M = 1609.344

# Región del monitor (izquierda, arriba, ancho, alto) en fracciones 0..1: la caja
# «N ft (pies)» bajo la mano, medida sobre una captura a 2560x1440. Ajustar con
# ``TSW6_HUD_OCR_REGION`` tras ``hud-ocr-calibrate``.
DEFAULT_REGION = (0.135, 0.085, 0.075, 0.040)
DEFAULT_INTERVAL_S = 0.5
MAX_READING_AGE_S = 3.0
MAX_PLAUSIBLE_M = 20000.0

_UNIT_M = {
    "ft": FT_TO_M,
    "fl": FT_TO_M,
    "pies": FT_TO_M,
    "pie": FT_TO_M,
    "feet": FT_TO_M,
    "yd": YD_TO_M,
    "yds": YD_TO_M,
    "mi": MI_TO_M,
    "km": 1000.0,
    "m": 1.0,
}
_DIST_RE = re.compile(
    r"(?P<num>\d[\d.,\s]*)\s*(?P<unit>ft|fl|pies|pie|feet|yds?|mi|km|m)\b",
    re.IGNORECASE,
)
_THOUSANDS_RE = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")
_DECIMAL_RE = re.compile(r"^\d+[.,]\d{1,2}$")


def parse_hud_distance(text: str) -> Optional[float]:
    """Distancia en metros desde el texto del HUD (``1.465 ft (pies)``, ``51 ft``, ``340 m``).

    En pies o yardas, ``1.465`` y ``1,465`` son miles; ``0,9`` / ``0.9`` son decimales.
    ``None`` si no hay una distancia reconocible o es absurda.
    """
    if not text:
        return None
    for match in _DIST_RE.finditer(text.replace("\n", " ")):
        num = re.sub(r"\s+", "", match.group("num")).strip(".,")
        unit = match.group("unit").lower()
        if not num:
            continue
        if _THOUSANDS_RE.match(num):
            value = float(re.sub(r"[.,]", "", num))
        elif _DECIMAL_RE.match(num):
            value = float(num.replace(",", "."))
        elif num.isdigit():
            value = float(num)
        else:
            continue
        meters = value * _UNIT_M[unit]
        if 0.0 < meters <= MAX_PLAUSIBLE_M:
            return round(meters, 2)
    return None


@dataclass(frozen=True)
class HudOcrReading:
    value_m: float
    raw: str
    t: float  # time.monotonic() de la captura


def find_tesseract() -> Optional[str]:
    """Ruta a ``tesseract.exe``: ``TSW6_TESSERACT``, PATH o instalación estándar de Windows."""
    env = os.environ.get("TSW6_TESSERACT", "").strip()
    if env and Path(env).is_file():
        return env
    from shutil import which

    found = which("tesseract")
    if found:
        return found
    for cand in (
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ):
        if cand.is_file():
            return str(cand)
    return None


def parse_region(text: str) -> tuple[float, float, float, float]:
    """``"l,t,w,h"`` (fracciones del monitor) → tupla; ``DEFAULT_REGION`` si no es válido."""
    try:
        parts = tuple(float(p) for p in text.replace(";", ",").split(","))
    except ValueError:
        return DEFAULT_REGION
    if len(parts) != 4 or any(not 0.0 <= p <= 1.0 for p in parts) or parts[2] <= 0 or parts[3] <= 0:
        return DEFAULT_REGION
    return parts  # type: ignore[return-value]


def _game_window_center() -> Optional[tuple[int, int]]:
    """Centro de la ventana visible de Train Sim World (Windows) o ``None``."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found: list[tuple[int, int]] = []

        def _cb(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if "train sim world" in buf.value.lower():
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                found.append(((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2))
            return True

        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(proto(_cb), 0)
        return found[0] if found else None
    except Exception:  # noqa: BLE001 - sin win32 se usa el monitor principal
        return None


def _pick_monitor(sct: Any, index: Optional[int]) -> dict[str, int]:
    monitors = sct.monitors
    if index is not None and 0 <= index < len(monitors):
        return monitors[index]
    center = _game_window_center()
    if center is not None:
        for mon in monitors[1:]:
            if (
                mon["left"] <= center[0] < mon["left"] + mon["width"]
                and mon["top"] <= center[1] < mon["top"] + mon["height"]
            ):
                return mon
    for mon in monitors[1:]:
        if mon.get("is_primary"):
            return mon
    return monitors[1] if len(monitors) > 1 else monitors[0]


def _preprocess(img: Any) -> Any:
    """Gris + contraste + ×3 + texto oscuro sobre fondo claro (lo que mejor lee Tesseract)."""
    from PIL import ImageOps, ImageStat

    gray = ImageOps.autocontrast(img.convert("L"))
    gray = gray.resize((gray.width * 3, gray.height * 3))
    if ImageStat.Stat(gray).mean[0] < 128:
        gray = ImageOps.invert(gray)
    return gray.point([0] * 141 + [255] * 115)


_OCR_CONFIG = "--psm 7 -c tessedit_char_whitelist=0123456789.,ftpiesmMIydkl() "


class HudOcrReader:
    """Hilo que lee el HUD cada ``interval_s`` y guarda la última lectura válida."""

    def __init__(
        self,
        *,
        region: tuple[float, float, float, float] = DEFAULT_REGION,
        monitor: Optional[int] = None,
        interval_s: float = DEFAULT_INTERVAL_S,
        tesseract_cmd: Optional[str] = None,
    ) -> None:
        self.region = region
        self.monitor = monitor
        self.interval_s = max(0.1, interval_s)
        self.tesseract_cmd = tesseract_cmd or find_tesseract()
        self._lock = threading.Lock()
        self._latest: Optional[HudOcrReading] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.error: Optional[str] = None
        self.reads = 0
        self.hits = 0
        self.last_raw = ""

    def start(self) -> bool:
        if self._thread is not None:
            return True
        if not self.tesseract_cmd:
            self.error = "Tesseract no encontrado (TSW6_TESSERACT / PATH)"
            return False
        self._thread = threading.Thread(target=self._run, name="hud-ocr", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def latest(self, *, max_age_s: float = MAX_READING_AGE_S) -> Optional[HudOcrReading]:
        with self._lock:
            reading = self._latest
        if reading is None or time.monotonic() - reading.t > max_age_s:
            return None
        return reading

    def diag(self) -> str:
        """Estado para el log: lecturas, aciertos, último texto OCR y error."""
        return f"reads={self.reads} hits={self.hits} last={self.last_raw!r} err={self.error}"

    def _crop_box(self, mon: dict[str, int]) -> dict[str, int]:
        left, top, width, height = self.region
        return {
            "left": mon["left"] + int(mon["width"] * left),
            "top": mon["top"] + int(mon["height"] * top),
            "width": max(8, int(mon["width"] * width)),
            "height": max(8, int(mon["height"] * height)),
        }

    def read_once(self, sct: Any) -> Optional[HudOcrReading]:
        import pytesseract
        from PIL import Image

        pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
        mon = _pick_monitor(sct, self.monitor)
        shot = sct.grab(self._crop_box(mon))
        t = time.monotonic()
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        raw = pytesseract.image_to_string(_preprocess(img), config=_OCR_CONFIG).strip()
        self.reads += 1
        self.last_raw = raw.replace(chr(10), ' ')[:40]
        value = parse_hud_distance(raw)
        if value is None:
            return None
        self.hits += 1
        return HudOcrReading(value_m=value, raw=raw.replace("\n", " "), t=t)

    def _run(self) -> None:
        try:
            import mss

            factory = getattr(mss, "MSS", None) or mss.mss
            with factory() as sct:
                while not self._stop.is_set():
                    started = time.monotonic()
                    try:
                        reading = self.read_once(sct)
                    except Exception as exc:  # noqa: BLE001 - un fallo de OCR no debe parar el agente
                        self.error = f"{type(exc).__name__}: {exc}"
                        reading = None
                    if reading is not None:
                        with self._lock:
                            self._latest = reading
                    self._stop.wait(max(0.0, self.interval_s - (time.monotonic() - started)))
        except Exception as exc:  # noqa: BLE001 - mss/PIL ausentes
            self.error = f"{type(exc).__name__}: {exc}"


def hud_ocr_from_env() -> Optional[HudOcrReader]:
    """Lector arrancado si ``TSW6_HUD_OCR=1``; ``None`` si está desactivado o no puede iniciar."""
    if os.environ.get("TSW6_HUD_OCR", "").strip().lower() not in ("1", "true", "yes", "on"):
        return None
    mon_raw = os.environ.get("TSW6_HUD_OCR_MONITOR", "").strip()
    try:
        interval = float(os.environ.get("TSW6_HUD_OCR_INTERVAL", DEFAULT_INTERVAL_S))
    except ValueError:
        interval = DEFAULT_INTERVAL_S
    reader = HudOcrReader(
        region=parse_region(os.environ.get("TSW6_HUD_OCR_REGION", "")),
        monitor=int(mon_raw) if mon_raw.isdigit() else None,
        interval_s=interval,
    )
    if not reader.start():
        print(f"AVISO: OCR del HUD desactivado: {reader.error}")
        return None
    return reader


def calibrate(out_dir: Path, reader: Optional[HudOcrReader] = None) -> dict[str, Any]:
    """Guarda captura del monitor + recorte (original y preprocesado) y devuelve la lectura.

    Se usa con el juego abierto y el marcador de parada visible para ajustar la región.
    """
    import mss
    from PIL import Image

    reader = reader or HudOcrReader(
        region=parse_region(os.environ.get("TSW6_HUD_OCR_REGION", ""))
    )
    if not reader.tesseract_cmd:
        raise RuntimeError("Tesseract no encontrado (TSW6_TESSERACT / PATH)")
    out_dir.mkdir(parents=True, exist_ok=True)
    factory = getattr(mss, "MSS", None) or mss.mss
    with factory() as sct:
        mon = _pick_monitor(sct, reader.monitor)
        full = sct.grab(mon)
        Image.frombytes("RGB", full.size, full.bgra, "raw", "BGRX").save(out_dir / "monitor.png")
        box = reader._crop_box(mon)
        crop = sct.grab(box)
        img = Image.frombytes("RGB", crop.size, crop.bgra, "raw", "BGRX")
        img.save(out_dir / "recorte.png")
        _preprocess(img).save(out_dir / "recorte_procesado.png")
        reading = reader.read_once(sct)
    return {
        "monitor": mon,
        "box": box,
        "region": reader.region,
        "reading_m": None if reading is None else reading.value_m,
        "raw": None if reading is None else reading.raw,
        "out_dir": str(out_dir),
    }
