"""
throttle_controller.py – Control de tracción (acelerador) para TSW6
====================================================================
Gestiona la maneta de tracción del Class 323 (PowerBrakeHandle, zona superior).

  Notch 0 = neutro (sin tracción)
  Notch 4 = tracción máxima
  Tecla A  = subir un notch (+)
  Tecla D  = bajar un notch (-), solo hasta neutro (0)
"""

import time
from typing import Optional

from tsw_keys import VK_A, VK_D, KEY_HOLD_MS, send_key


class ThrottleController:
    """Controla la maneta de tracción (notch 0-4)."""

    MAX_NOTCH = 4

    def __init__(self) -> None:
        self.notch: int = 0   # 0 = neutro, 4 = tracción máxima (estimado)

    # ── Estado ──────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """True cuando hay tracción aplicada (notch > 0)."""
        return self.notch > 0

    # ── Acciones ─────────────────────────────────────────────────────────────

    def accelerate(self, hwnd: Optional[int]) -> bool:
        """Sube 1 notch de tracción. Devuelve True si actuó."""
        if hwnd and self.notch < self.MAX_NOTCH:
            send_key(hwnd, VK_A)
            self.notch += 1
            return True
        return False

    def coast(self, hwnd: Optional[int], steps: int = 1) -> bool:
        """Baja `steps` notches de tracción (hasta neutro).
        Envía una pulsación independiente por muesca para evitar desincronización.
        Devuelve True si actuó."""
        actual = min(steps, self.notch)
        if hwnd and actual > 0:
            for _ in range(actual):
                send_key(hwnd, VK_D)
            self.notch -= actual
            return True
        return False

    def release_all(self, hwnd: Optional[int]) -> None:
        """Lleva la tracción a neutro (notch 0), paso a paso."""
        pause = KEY_HOLD_MS / 1000.0 + 0.1
        while self.notch > 0:
            if not self.coast(hwnd):
                break   # hwnd no válido: no se puede enviar tecla, salir
            time.sleep(pause)
