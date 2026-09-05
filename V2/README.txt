TSW6 proyecto V2
================

Todo el producto nuevo vive aqui. No mezclar con tsw6/autopilot ni tsw6/braking.

Estructura:
  V2/tsw6v2/       codigo Python
  V2/tsw6v2/bridge/  GetData + IPC (contrato D2, código propio)
  V2/tests/        pytest

Comandos (desde raiz repo):
  V2\test_pytest.bat                          todos los tests V2
  V2\test_pytest.bat V2\tests\test_foo.py -v  un archivo

  python -m pytest V2/tests/ -q               (pytest.ini pone pythonpath=. V2)
  python V2/tests/test_foo.py                 (ejecuta pytest de ese archivo; ver salida)
  python -m tsw6v2 console
  python -m tsw6v2 gui
  python -m tsw6v2 test-ipc

O: V2\run.bat  |  V2\run_gui.bat  |  V2\test_ipc.bat
    V2\run_p1_session.bat limit cross-city   (P1 + JSONL + investigate)

Legacy v1 = referencia en tsw6/ — no fiarse para producto nuevo.
