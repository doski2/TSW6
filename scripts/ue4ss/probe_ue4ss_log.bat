@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title TSW6 - Monitor UE4SS probe (con log)

cd /d "%~dp0..\.."
set "PYTHONPATH=%CD%"

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    for %%c in (py python) do (
        if not defined PY (
            %%c -3 --version >nul 2>&1 && set "PY=%%c -3"
        )
    )
)
if not defined PY (
    for %%c in (python) do (
        if not defined PY (
            %%c --version >nul 2>&1 && set "PY=%%c"
        )
    )
)
if not defined PY (
    echo [ERROR] Python no encontrado.
    pause
    exit /b 1
)

echo.
echo  Graba telemetria en logs\ue4ss_probe_*.txt
echo  GetData: %TEMP%\TSW6Bridge\GetData.txt
echo  1. TSW6 en cabina con probe activo
echo  2. Ctrl+C para cerrar
echo.

%PY% -c "import colorama" >nul 2>&1 || %PY% -m pip install --quiet colorama
%PY% -m tsw6.telemetry.tsw_ue4ss_reader --log --simple %*

if errorlevel 1 pause
