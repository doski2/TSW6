@echo off
chcp 65001 >nul
title TSW6 - Diagnostico de mandos (API)

cd /d "%~dp0"

echo.
echo  El diagnostico RailBridge (companion CMP) esta archivado en:
echo    archive\railbridge\
echo.
echo  Usando monitor API TSW (-HTTPAPI) en su lugar.
echo  Arranca TSW6 con -HTTPAPI y sube al tren antes de continuar.
echo.
pause

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

%PY% -c "import colorama" >nul 2>&1 || %PY% -m pip install --quiet colorama requests
%PY% tsw_monitor.py
