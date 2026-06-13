@echo off
chcp 65001 >nul
title TSW6 Monitor de Aprendizaje

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
%PY% -c "import requests" >nul 2>&1
if errorlevel 1 (
    echo  Instalando dependencias...
    %PY% -m pip install --quiet requests
)

:menu
cls
echo.
echo  ════════════════════════════════════════════════════════════
echo    TSW6 — MONITOR DE APRENDIZAJE GUIADO
echo  ════════════════════════════════════════════════════════════
echo.
echo    El monitor te guia para calibrar cada muesca del tren.
echo    Conduce manualmente siguiendo las instrucciones en pantalla.
echo.
echo    1. Continuar aprendizaje — pasajeros (vel. min. 5 mph)
echo    2. Continuar aprendizaje — mercancias (vel. min. 2 mph)
echo    3. Empezar de cero — pasajeros
echo    4. Empezar de cero — mercancias
echo    5. Salir
echo.
set /p "OP=  Opcion [1]: "
if "%OP%"=="" set "OP=1"

if "%OP%"=="1" goto continuar
if "%OP%"=="2" goto continuar_freight
if "%OP%"=="3" goto reset
if "%OP%"=="4" goto reset_freight
if "%OP%"=="5" exit /b 0
goto menu

:continuar
cls
%PY% learn_monitor.py
goto fin

:continuar_freight
cls
%PY% learn_monitor.py --freight
goto fin

:reset
cls
%PY% learn_monitor.py --reset
goto fin

:reset_freight
cls
%PY% learn_monitor.py --reset --freight
goto fin

:fin
echo.
pause
exit /b 0
