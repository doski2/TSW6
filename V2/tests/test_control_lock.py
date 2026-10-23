"""``control_lock``: solo un controlador de mandos a la vez (mutex de Windows)."""

from __future__ import annotations

import ctypes
import sys
import uuid

import pytest

from tsw6v2 import control_lock

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="mutex de Windows")


@pytest.fixture(autouse=True)
def _mutex_propio(monkeypatch: pytest.MonkeyPatch):
    """Nombre único: el test nunca choca con una GUI real abierta."""
    monkeypatch.setattr(control_lock, "_MUTEX_NAME", f"TSW6_TEST_{uuid.uuid4().hex}")
    monkeypatch.setattr(control_lock, "_handle", None)
    yield
    if control_lock._handle:
        ctypes.windll.kernel32.CloseHandle(control_lock._handle)


def test_toma_el_candado_y_es_idempotente() -> None:
    control_lock.acquire_control_lock()
    first = control_lock._handle
    assert first
    control_lock.acquire_control_lock()
    assert control_lock._handle == first


def test_otro_proceso_con_el_candado_lanza_error() -> None:
    k32 = ctypes.windll.kernel32
    other = k32.CreateMutexW(None, False, control_lock._MUTEX_NAME)
    try:
        with pytest.raises(control_lock.ControlLockError, match="otro controlador"):
            control_lock.acquire_control_lock()
        assert control_lock._handle is None
    finally:
        k32.CloseHandle(other)


def test_tras_liberar_se_puede_volver_a_tomar() -> None:
    k32 = ctypes.windll.kernel32
    other = k32.CreateMutexW(None, False, control_lock._MUTEX_NAME)
    k32.CloseHandle(other)
    control_lock.acquire_control_lock()
    assert control_lock._handle
