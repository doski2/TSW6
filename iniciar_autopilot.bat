@echo off
chcp 65001 >nul
title TSW6 Autopilot

:: ── Cambiar al directorio del .bat (funciona desde cualquier sitio) ──────────
cd /d "%~dp0"

:: ── Detectar Python 3.9+ ─────────────────────────────────────────────────────
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
    echo  Descargalo en https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: ── Instalar dependencias si faltan ──────────────────────────────────────────
%PY% -c "import requests, colorama" >nul 2>&1
if errorlevel 1 (
    echo  Instalando dependencias...
    %PY% -m pip install --quiet requests colorama
    if errorlevel 1 (
        echo  [ERROR] No se pudieron instalar las dependencias.
        pause
        exit /b 1
    )
    echo  Dependencias instaladas correctamente.
)

:menu
cls
echo.
echo  ^+======================================================^+
echo  ^|       TSW6 AUTOPILOT  -  Menu de inicio             ^|
echo  ^+======================================================^+
echo.
echo   1.  Autopilot ACTIVO   ^(sigue limite de via^)
echo   2.  Velocidad maxima personalizada
echo   3.  Solo monitorizar   ^(sin enviar controles^)
echo   4.  Modo MANUAL        ^(introduce velocidad por teclado^)
echo   5.  Monitor de telemetria  ^(tsw_monitor.py^)
echo   6.  Salir
echo.
set /p opcion="  Elige una opcion (1-6): "

if "%opcion%"=="1" goto op1
if "%opcion%"=="2" goto op2
if "%opcion%"=="3" goto op3
if "%opcion%"=="4" goto op4
if "%opcion%"=="5" goto op5
if "%opcion%"=="6" exit /b 0
echo  Opcion no valida.
timeout /t 1 >nul
goto menu

:op1
echo.
echo  CONSEJO: Activa el boton CMP en RailBridge para telemetria automatica.
echo  Si no, el autopilot pedira los datos manualmente.
echo.
pause
%PY% tsw_autopilot.py --profile
echo.
echo  Analizando datos de calibracion...
echo.
%PY% analyze.py --apply
goto fin

:op2
echo.
set /p vel="  Velocidad maxima en mph (ej: 60): "
if "%vel%"=="" goto menu
%PY% tsw_autopilot.py --target %vel%
goto fin

:op3
%PY% tsw_autopilot.py --no-control
goto fin

:op4
%PY% tsw_autopilot.py --manual
goto fin

:op5
%PY% tsw_monitor.py
goto fin

:fin
echo.
pause
goto menu
