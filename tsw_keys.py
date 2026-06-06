"""
tsw_keys.py – Infraestructura de envío de teclas para TSW6
===========================================================
Envía teclas mediante SendInput (inyección a nivel hardware).
Compatible con motores UE4/UE5 que ignoran PostMessage/WM_KEYDOWN.

Uso: TSW6 debe estar en primer plano para recibir las teclas.
"""

import ctypes
import time

# ── Windows API ───────────────────────────────────────────────────────────────

user32 = ctypes.windll.user32

_INPUT_KEYBOARD  = 1
_KEYEVENTF_KEYUP = 0x0002


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_ulonglong),   # 8 bytes fijos (puntero en x64)
    ]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("_pad", ctypes.c_ubyte * 28)]
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


# ── Virtual-key codes (Windows) ───────────────────────────────────────────────

VK_A          = 0x41   # power_increase  (maneta de tracción +)
VK_D          = 0x44   # power_decrease  (maneta de tracción -)
VK_APOSTROPHE = 0xDE   # train_brake_increase  (tecla ')
VK_SEMICOLON  = 0xBA   # train_brake_decrease  (tecla ;)

# Duración de pulsación por notch (Class 323)
KEY_HOLD_MS = 350      # ~350 ms = 1 notch en el PowerBrakeHandle


# ── Función de envío ──────────────────────────────────────────────────────────

def send_key(hwnd: int, vk_code: int, hold_ms: int = KEY_HOLD_MS) -> None:
    """Envía tecla vía SendInput (bloquea durante hold_ms).
    `hwnd` se conserva por compatibilidad pero no se usa; SendInput es global."""
    scan = user32.MapVirtualKeyW(vk_code, 0)

    def _inp(flags: int) -> _INPUT:
        x = _INPUT()
        x.type = _INPUT_KEYBOARD
        x.u.ki.wVk   = vk_code
        x.u.ki.wScan = scan
        x.u.ki.dwFlags = flags
        return x

    user32.SendInput(1, ctypes.byref(_inp(0)), ctypes.sizeof(_INPUT))
    time.sleep(hold_ms / 1000.0)
    user32.SendInput(1, ctypes.byref(_inp(_KEYEVENTF_KEYUP)), ctypes.sizeof(_INPUT))
