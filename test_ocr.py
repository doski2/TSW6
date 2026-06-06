"""
test_ocr.py — Herramienta de calibración del OCR.

Captura la región del panel de tareas TSW, la guarda como PNG para
revisión visual y ejecuta el OCR para ver qué texto se lee.

Uso (con TSW abierto):
    python test_ocr.py
    python test_ocr.py --loop      # repetir cada 2 s hasta Ctrl+C

El PNG guardado (ocr_debug.png) muestra exactamente qué se manda a
Tesseract tras el preprocesado. Si el texto no coincide con el panel,
ajusta _ROI_* en tsw_ocr.py.
"""

import sys
import time
import argparse

# Reutilizar la lógica de tsw_ocr
from tsw_ocr import (
    _client_screen_rect, _parse_distance,
    _ROI_LEFT, _ROI_TOP, _ROI_W, _ROI_H,
    _OCR_AVAILABLE, _TESS_CONFIG, _LANCZOS,
)
from tsw_autopilot import find_tsw_window

try:
    import mss as _mss  # type: ignore[import-untyped]
    from PIL import Image as _Img, ImageOps as _IOps  # type: ignore[import-untyped]
except ImportError:
    print("Faltan mss/Pillow")
    sys.exit(1)

OUT_RAW  = "ocr_raw.png"     # captura sin preprocesar
OUT_PROC = "ocr_debug.png"   # imagen preprocesada que ve Tesseract


def capture_and_show(hwnd: int) -> None:
    rect = _client_screen_rect(hwnd)
    if rect is None:
        print("No se pudo obtener el rect de la ventana TSW")
        return
    wx, wy, ww, wh = rect
    left   = wx + int(ww * _ROI_LEFT)
    top    = wy + int(wh * _ROI_TOP)
    width  = max(1, int(ww * _ROI_W))
    height = max(1, int(wh * _ROI_H))

    print(f"  Ventana TSW : ({wx}, {wy})  {ww}×{wh} px")
    print(f"  ROI captura : left={left} top={top}  {width}×{height} px")

    with _mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top,
                         "width": width, "height": height})
        raw = _Img.frombytes("RGB", (shot.width, shot.height), shot.rgb)

    raw.save(OUT_RAW)
    print(f"  Guardado    : {OUT_RAW}  (imagen original sin procesar)")

    # Mismo preprocesado que usa TswOcr
    proc = raw.resize((raw.width * 3, raw.height * 3), _LANCZOS)
    proc = proc.convert("L")
    proc = _IOps.invert(proc)
    proc = proc.point([255 if i > 80 else 0 for i in range(256)])
    proc.save(OUT_PROC)
    print(f"  Guardado    : {OUT_PROC}  (imagen que ve Tesseract)")

    import pytesseract as _tess  # type: ignore[import-untyped]
    from tsw_ocr import _TESSERACT_CMD
    _tess.pytesseract.tesseract_cmd = _TESSERACT_CMD

    text = _tess.image_to_string(proc, config=_TESS_CONFIG).strip()
    dist = _parse_distance(text)

    print(f"\n  OCR texto   : {text!r}")
    if dist is not None:
        print(f"  OCR dist    : {dist:.1f} m  ({dist/1609.344:.3f} mi)")
    else:
        print("  OCR dist    : (no se detectó distancia)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true",
                        help="Repetir cada 2 s hasta Ctrl+C")
    args = parser.parse_args()

    if not _OCR_AVAILABLE:
        print("OCR no disponible — verifica mss, Pillow y pytesseract")
        sys.exit(1)

    hwnd = find_tsw_window()
    if not hwnd:
        print("TSW no encontrado. Abre el juego y vuelve a ejecutar.")
        sys.exit(1)
    print(f"\nVentana TSW encontrada (hwnd=0x{hwnd:x})\n")

    try:
        while True:
            capture_and_show(hwnd)
            if not args.loop:
                break
            print()
            time.sleep(2.0)
    except KeyboardInterrupt:
        pass

    print(f"\nAbre {OUT_RAW} y {OUT_PROC} para revisar la región capturada.")


if __name__ == "__main__":
    main()
