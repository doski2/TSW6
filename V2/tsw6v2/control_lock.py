"""Instancia única del controlador de mandos (GUI o consola).

Dos procesos que envían órdenes IPC a la vez se pisan y hacen los mandos
inestables. Usa un mutex con nombre de Windows: el sistema lo libera solo
al terminar el proceso, aunque se cierre de forma brusca.
En otros sistemas no hay candado (no aplica a TSW6 en Windows).
"""

from __future__ import annotations

import sys
from typing import Optional

_MUTEX_NAME = "Local\\TSW6_V2_CONTROL"
_ERROR_ALREADY_EXISTS = 183
_handle: Optional[int] = None


class ControlLockError(RuntimeError):
    """Ya hay otro controlador activo."""


def acquire_control_lock() -> None:
    """Toma el candado o lanza ``ControlLockError`` si otro proceso lo tiene."""
    global _handle
    if _handle is not None or sys.platform != "win32":
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        raise ControlLockError("no se pudo crear el candado de control")
    if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        raise ControlLockError(
            "ya hay otro controlador V2 activo (GUI o validar_estacion_diag.bat). "
            "Cierra esa sesión antes de iniciar otra."
        )
    _handle = handle
