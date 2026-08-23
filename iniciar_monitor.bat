@echo off
chcp 65001 >nul
title TSW6 API Monitor

cd /d "%~dp0"

set "PY="
for %%c in (python3 python py) do (
    if not defined PY (
        %%c --version >nul 2>&1 && (
            for /f "tokens=2" %%v in ('%%c --version 2^>^&1') do (
                for /f "tokens=1,2 delims=." %%a in ("%%v") do (
                    if %%a geq 3 if %%b geq 9 set "PY=%%c"
                )
            )
        )
    )
)
if not defined PY (
    echo.
    echo  [ERROR] No se encontro Python 3.9+
    pause
    exit /b 1
)

%PY% -c "import requests, colorama" >nul 2>&1
if errorlevel 1 (
    echo  Instalando dependencias...
    %PY% -m pip install --quiet requests colorama
)

echo.
echo  ============================================================
echo    TSW6 API Monitor  (-HTTPAPI)
echo    TSW en cabina antes de continuar.
echo  ============================================================
echo.
echo  Modos:
echo    monitor   - Dashboard en tiempo real (defecto)
echo    discover  - Endpoints y datos
echo    snapshot  - Captura JSON
echo    raw       - JSON continuo
echo.
set /p MODO="  Modo [monitor]: "
if "%MODO%"=="" set MODO=monitor

%PY% tsw_monitor.py %MODO%
pause
