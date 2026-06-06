"""
brake_controller.py – Control de freno para TSW6
=================================================
Gestiona la maneta de freno del Class 323 (PowerBrakeHandle, zona inferior).

  Notch 0 = sin freno (neutro)
  Notch 4 = freno total
  Tecla D  = aplicar más freno (+)
  Tecla A  = soltar freno (-)
"""

import time
from typing import Optional

from tsw_keys import VK_A, VK_D, KEY_HOLD_MS, send_key


class BrakeController:
    """Controla la maneta de freno (notch 0-4)."""

    MAX_NOTCH = 4

    def __init__(self) -> None:
        self.notch: int = 0   # 0 = sin freno, 4 = freno total (estimado)

    # ── Estado ──────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """True cuando hay freno aplicado (notch > 0)."""
        return self.notch > 0

    # ── Acciones ─────────────────────────────────────────────────────────────

    def apply(self, hwnd: Optional[int], steps: int = 2) -> bool:
        """Aplica `steps` notches de freno (por defecto +2 para respuesta rápida).
        Envía una pulsación independiente por muesca para evitar desincronización.
        Devuelve True si actuó."""
        actual = min(steps, self.MAX_NOTCH - self.notch)
        if hwnd and actual > 0:
            for _ in range(actual):
                send_key(hwnd, VK_D)
            self.notch += actual
            return True
        return False

    def release(self, hwnd: Optional[int]) -> bool:
        """Suelta 1 notch de freno. Devuelve True si actuó."""
        if hwnd and self.notch > 0:
            send_key(hwnd, VK_A)
            self.notch -= 1
            return True
        return False

    def release_all(self, hwnd: Optional[int]) -> None:
        """Libera todo el freno (notch 0), paso a paso."""
        pause = KEY_HOLD_MS / 1000.0 + 0.1
        while self.notch > 0:
            if not self.release(hwnd):
                break   # hwnd no válido: no se puede enviar tecla, salir
            time.sleep(pause)
