@echo off
REM Tests V2 — desde raiz repo con PYTHONPATH correcto.
REM Uso: V2\test_pytest.bat
REM      V2\test_pytest.bat V2\tests\test_session_report.py -v
cd /d "%~dp0.."
set "PYTHONPATH=%CD%;%CD%\V2"
if exist "%CD%\.venv\Scripts\python.exe" (
    set "PY=%CD%\.venv\Scripts\python.exe"
) else (
    set "PY=python"
)
if "%~1"=="" (
    "%PY%" -m pytest V2\tests\ -q
) else (
    "%PY%" -m pytest %*
)
exit /b %ERRORLEVEL%
