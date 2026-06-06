"""
tsw_ocr.py — OCR del panel de tareas TSW.

Lee la distancia al marcador de parada "DETENGASE EN EL LUGAR" directamente
desde la pantalla del juego, con la precisión que muestra el juego (pies o
metros en el tramo final → ~0.3 m de resolución vs ~1 m de la API).

Dependencias (ya instaladas):
    mss, Pillow, pytesseract  +  Tesseract 5.x en C:\\Program Files\\Tesseract-OCR

Sin alguna de ellas la clase TswOcr se instancia pero devuelve None siempre.

Uso:
    from tsw_ocr import TswOcr
    ocr = TswOcr(hwnd)
    ...
    dist_m = ocr.get_distance()   # float metros, o None si sin datos
    ...
    ocr.stop()
"""

import ctypes
import ctypes.wintypes as wt
import logging
import re
import threading
import time
from typing import Optional

_log = logging.getLogger("tsw.ocr")

# ── Ruta al binario Tesseract ─────────────────────────────────────────────────
_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ── imports opcionales ────────────────────────────────────────────────────────
try:
    import mss as _mss              # type: ignore[import-untyped]
    _MSS_OK = True
except ImportError:
    _MSS_OK = False

try:
    from PIL import Image as _Img, ImageOps as _IOps   # type: ignore[import-untyped]
    _PIL_OK = True
    try:
        _Resampling = getattr(_Img, "Resampling", None)
        if _Resampling is not None:
            _LANCZOS = getattr(_Resampling, "LANCZOS", None)
        else:
            _LANCZOS = getattr(_Img, "LANCZOS", None)
    except AttributeError:
        _LANCZOS = None
except ImportError:
    _PIL_OK = False
    _LANCZOS = None

try:
    import pytesseract as _tess    # type: ignore[import-untyped]
    _tess.pytesseract.tesseract_cmd = _TESSERACT_CMD
    _TESS_OK = True
except ImportError:
    _TESS_OK = False

_OCR_AVAILABLE = _MSS_OK and _PIL_OK and _TESS_OK
if not _OCR_AVAILABLE:
    _missing = [n for n, ok in [("mss", _MSS_OK), ("Pillow", _PIL_OK),
                                 ("pytesseract", _TESS_OK)] if not ok]
    _log.warning("TswOcr: OCR desactivado — falta(n): %s", ", ".join(_missing))

# ── expresiones regulares de distancia ───────────────────────────────────────
# Formatos posibles en el panel de tareas TSW:
#   "4.2 mi"  →  millas  (zona de largo alcance)
#   "255 yd"  →  yardas  (tramo final < ~0.6 mi, UK)
#   "500 ft"  →  pies    (tramo final, resolución ~0.3 m)
#   "150 m"   →  metros  (modo métrico con unidad)
#   "150"     →  metros  (DMI en modo métrico sin unidad explícita, < 200 m)
_PAT_MI = re.compile(r"(\d+[.,]?\d*)\s*mi\b",        re.IGNORECASE)
_PAT_YD = re.compile(r"(\d+)\s*yd\b",                 re.IGNORECASE)
_PAT_FT = re.compile(r"(\d+)\s*ft\b",                 re.IGNORECASE)
_PAT_M  = re.compile(r"(\d+[.,]?\d*)\s*m\b(?!\s*i)", re.IGNORECASE)
# Último recurso: entero suelto de 2-4 dígitos sin unidad.
# El DMI TSW/UK muestra la distancia al marcador de parada en metros pero
# Tesseract a veces omite la "m" final.  Solo se acepta si el texto completo
# es exactamente ese número (evita falsos positivos en textos mixtos).
_PAT_BARE_M = re.compile(r"^\s*(\d{2,4})\s*$")
_MI_M   = 1_609.344
_YD_M   = 0.9144
_FT_M   = 0.3048

# ── región del panel de tareas (fracción del área cliente de la ventana) ─────
# Posición medida en PhotoDemon sobre captura 1922×1112:
#   x=252 y=54  w=95  h=118  → fracciones del área cliente TSW
_ROI_LEFT = 0.131
_ROI_TOP  = 0.049
_ROI_W    = 0.049
_ROI_H    = 0.106

# ── configuración Tesseract ───────────────────────────────────────────────────
# psm 11 = texto disperso: encuentra texto en cualquier parte de la imagen
# (necesario porque el icono ocupa el 60% superior del ROI).
# Whitelist incluye 'y','d' para leer 'yd' (yardas, < ~0.6 mi en rutas UK).
_TESS_CONFIG = r"--psm 11 -c tessedit_char_whitelist=0123456789.,mMfFiItTyYdD "

# ── Win32 ─────────────────────────────────────────────────────────────────────
_u32 = ctypes.windll.user32


class _POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


def _client_screen_rect(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    """Devuelve (left, top, width, height) del área cliente en coords de pantalla."""
    pt = _POINT(0, 0)
    if not _u32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    rc = _RECT()
    if not _u32.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    return (int(pt.x), int(pt.y), int(rc.right), int(rc.bottom))


# ── lógica de distancia ───────────────────────────────────────────────────────

def _parse_distance(text: str) -> Optional[float]:
    """Extrae la primera distancia del texto OCR y la convierte a metros."""
    m = _PAT_MI.search(text)
    if m:
        return float(m.group(1).replace(",", ".")) * _MI_M
    m = _PAT_YD.search(text)
    if m:
        return int(m.group(1)) * _YD_M
    m = _PAT_FT.search(text)
    if m:
        return int(m.group(1)) * _FT_M
    m = _PAT_M.search(text)
    if m:
        return float(m.group(1).replace(",", "."))
    # Último recurso: número suelto sin unidad → metros
    # (el DMI UK muestra sólo dígitos en el tramo final; la "m" no es detectada)
    m = _PAT_BARE_M.match(text)
    if m:
        return float(m.group(1))
    return None


def _detect_task(img: "_Img.Image") -> Optional[str]:
    """
    Detecta el tipo de tarea en el ROI preprocesado (invertido+umbralizado).
    Analiza el ratio de píxeles blancos en el 60% superior:
      stop sign  (hexágono grande)  → ratio alto  → "stop"
      boarding   (ícono pequeño)    → ratio bajo  → "board"
      sin tarea                     → ratio ínfimo → None
    """
    w, h = img.size
    top_h = max(1, int(h * 0.60))
    top = img.crop((0, 0, w, top_h))
    pixels = list(top.getdata())
    ratio = pixels.count(255) / len(pixels) if pixels else 0.0
    # ratio debug removed (was ~2 logs/sec noise; use logging.TRACE if needed)
    if ratio > 0.30:
        return "stop"
    if ratio > 0.08:
        return "board"
    return None


def _capture_and_ocr(hwnd: int) -> "tuple[Optional[float], Optional[str]]":
    """Captura el panel de tareas. Devuelve (distancia_m, tipo_tarea). Síncrono."""
    rect = _client_screen_rect(hwnd)
    if rect is None:
        return None, None
    wx, wy, ww, wh = rect
    if ww <= 0 or wh <= 0:
        return None, None

    left   = wx + int(ww * _ROI_LEFT)
    top    = wy + int(wh * _ROI_TOP)
    width  = max(1, int(ww * _ROI_W))
    height = max(1, int(wh * _ROI_H))

    with _mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top,
                         "width": width, "height": height})
        img = _Img.frombytes("RGB", (shot.width, shot.height), shot.rgb)

    # Preprocesado: escalar 3×, gris, invertir (claro→oscuro), umbral duro.
    # Tesseract rinde mejor con texto negro sobre fondo blanco.
    img = img.resize((img.width * 3, img.height * 3), _LANCZOS)
    img = img.convert("L")
    img = _IOps.invert(img)
    img = img.point([255 if i > 80 else 0 for i in range(256)])

    task = _detect_task(img)
    text = _tess.image_to_string(img, config=_TESS_CONFIG).strip()
    if text:
        _log.debug("OCR text: %r  task=%s", text[:120], task)
    return _parse_distance(text), task


# ── Clase principal ───────────────────────────────────────────────────────────

class TswOcr:
    """
    Hilo de fondo que captura y hace OCR del panel de tareas TSW a ~2 Hz.

    Expone:
        get_distance() → float metros o None
        stop()         → detiene el hilo de fondo

    Si las dependencias no están instaladas el constructor no lanza excepción;
    get_distance() simplemente devuelve None siempre.
    """

    POLL_S     = 0.5   # intervalo entre lecturas OCR
    RESULT_TTL = 4.0   # segundos — ignorar resultado sin actualizar
    # Lecturas > 3 km son casi siempre millas mal parseadas (p. ej. "4,8mi")
    MAX_DIST_M = 3_000.0

    def __init__(self, hwnd: int) -> None:
        self._hwnd       = hwnd
        self._dist: Optional[float] = None
        self._dist_ts    = 0.0
        self._task: Optional[str] = None
        self._task_ts    = 0.0
        self._lock       = threading.Lock()
        self._stop_ev    = threading.Event()
        self._active     = _OCR_AVAILABLE
        self._last_logged_dist: Optional[float] = None  # throttle OCR distance logging

        if _OCR_AVAILABLE:
            t = threading.Thread(target=self._run, name="tsw-ocr", daemon=True)
            t.start()
            _log.info("TswOcr iniciado (hwnd=0x%x)", hwnd)
        else:
            _log.debug("TswOcr desactivado")

    # ── API pública ────────────────────────────────────────────────────────────

    def get_distance(self) -> Optional[float]:
        """
        Última distancia OCR al marcador de parada en metros.
        Devuelve None si el OCR no está disponible, no se detectó
        ninguna distancia o el último resultado tiene más de RESULT_TTL segundos.
        """
        if not self._active:
            return None
        with self._lock:
            if time.monotonic() - self._dist_ts > self.RESULT_TTL:
                return None
            return self._dist

    def get_task(self) -> Optional[str]:
        """
        Tipo de tarea activa: 'stop' | 'board' | None.
        'stop'  → icono de parada (DETENGASE EN EL LUGAR) — puertas cerradas.
        'board' → icono de embarque (CARGAR VIAJEROS)    — puertas abiertas.
        None    → sin tarea visible o OCR no disponible.
        """
        if not self._active:
            return None
        with self._lock:
            if time.monotonic() - self._task_ts > self.RESULT_TTL:
                return None
            return self._task

    def stop(self) -> None:
        """Señaliza el hilo OCR para que termine."""
        self._stop_ev.set()

    # ── hilo interno ───────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_ev.is_set():
            t0 = time.monotonic()
            try:
                dist, task = _capture_and_ocr(self._hwnd)
                now = time.monotonic()
                with self._lock:
                    if dist is not None:
                        if dist > self.MAX_DIST_M:
                            _log.debug(
                                "OCR rechazado (%.0f m > máx %.0f m)",
                                dist, self.MAX_DIST_M,
                            )
                            dist = None
                        else:
                            self._dist    = dist
                            self._dist_ts = now
                    if task is not None:
                        self._task    = task
                        self._task_ts = now
                if dist is not None:
                    # Only log when distance changes significantly (>5m)
                    _should_log = (self._last_logged_dist is None
                                   or abs(dist - self._last_logged_dist) > 5.0)
                    if _should_log:
                        _log.debug("OCR → %.1f m  task=%s", dist, task)
                        self._last_logged_dist = dist
            except Exception as exc:
                _log.debug("OCR error: %s", exc)
            elapsed = time.monotonic() - t0
            self._stop_ev.wait(max(0.0, self.POLL_S - elapsed))
