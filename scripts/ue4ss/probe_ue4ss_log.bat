@echo off
chcp 65001 >nul
title TSW6 - Monitor UE4SS probe (con log)

cd /d "%~dp0..\.."
set "PYTHONPATH=%CD%"

set "PY="
for %%c in (python3 python py) do (
    if not defined PY (
        %%c --version >nul 2>&1 && set "PY=%%c"
    )
)
if not defined PY (
    echo [ERROR] Python no encontrado.
    pause
    exit /b 1
)

echo.
echo  Graba telemetria en logs\ue4ss_probe_*.txt
echo  1. TSW6 en cabina con el probe activo
echo  2. Mueve el mando A/D unos segundos
echo  3. Ctrl+C - copia el archivo .txt y pasalo al chat
echo.

%PY% -c "import colorama" >nul 2>&1 || %PY% -m pip install --quiet colorama
%PY% -m tsw6.telemetry.tsw_ue4ss_reader --log %*
