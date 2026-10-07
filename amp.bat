@echo off
setlocal EnableDelayedExpansion
REM Informe amps desde log probe. Sin argumentos = ultimo logs\ue4ss_probe_*.txt
cd /d "%~dp0"
set "PYTHONPATH=%CD%"

set "PY="
if exist "%CD%\.venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
if not defined PY set "PY=python"

echo.
"%PY%" scripts\tools\amp.py %*
set "ERR=!ERRORLEVEL!"

echo.
if !ERR! NEQ 0 (
    echo  [ERROR] amp.py termino con codigo !ERR!
) else (
    echo  Listo. Para guardar informe: amp.bat --write-report
)
echo.
pause
exit /b !ERR!
