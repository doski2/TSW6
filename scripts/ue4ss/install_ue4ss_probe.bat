@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title TSW6 - Instalar TelemetryProbeMod (UE4SS)

cd /d "%~dp0..\.."
set "PYTHONPATH=%CD%"

set "TSW_ROOT=C:\Program Files (x86)\Steam\steamapps\common\Train Sim World 6"
if not "%~1"=="" set "TSW_ROOT=%~1"

set "MODS_SRC=%CD%\mods\TelemetryProbeMod\Scripts"
set "MODS_DST=%TSW_ROOT%\WindowsNoEditor\TS2Prototype\Binaries\Win64\Mods"
set "MODS_TXT=%MODS_DST%\mods.txt"
set "LUA_DST=%MODS_DST%\TelemetryProbeMod\Scripts"
set "LUA_SRC_MAIN=%MODS_SRC%\main.lua"

echo.
echo  TelemetryProbeMod - instalador UE4SS
echo  Repo:   "%MODS_SRC%"
echo  Juego:  "%LUA_DST%"
echo.

if not exist "%LUA_SRC_MAIN%" (
    echo [ERROR] No se encuentra mods\TelemetryProbeMod\Scripts\main.lua en el repo.
    pause
    exit /b 1
)

if not exist "%MODS_DST%" (
    echo [ERROR] No existe la carpeta Mods del juego.
    echo         TSW6 + UE4SS esperados en:
    echo         "%TSW_ROOT%"
    echo.
    echo         install_ue4ss_probe.bat "RUTA\Train Sim World 6"
    pause
    exit /b 1
)

if not exist "%LUA_DST%" mkdir "%LUA_DST%"
xcopy /Y /E /I "%MODS_SRC%\*" "%LUA_DST%\" >nul
if errorlevel 1 (
    echo [ERROR] Fallo xcopy. Prueba como Administrador.
    pause
    exit /b 1
)

findstr /C:"PROBE_BUILD" "%LUA_DST%\main.lua" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] main.lua del juego sin PROBE_BUILD.
    pause
    exit /b 1
)
echo  Version en juego:
findstr /C:"PROBE_BUILD" "%LUA_DST%\config.lua"
findstr /C:"PROBE_BUILD" "%LUA_SRC_MAIN%"

findstr /C:"lever_notch=" "%LUA_DST%\telemetry.lua" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] telemetry.lua sin lever_notch — mod incompleto.
    pause
    exit /b 1
)

findstr /I /C:"TelemetryProbeMod" "%MODS_TXT%" >nul 2>&1
if errorlevel 1 (
    echo TelemetryProbeMod : 1>> "%MODS_TXT%"
    echo  Anadido TelemetryProbeMod : 1 en mods.txt
) else (
    echo  TelemetryProbeMod ya estaba en mods.txt
)

echo.
echo  [OK] TelemetryProbeMod instalado (todos los .lua de Scripts/)
echo       Reinicia TSW6 si estaba abierto.
echo.
echo  En cabina:
echo    Probe AUTO-START al cargar escenario ^(F7 apaga^)
echo    F8  volcar linea al log + GetData.txt
echo    Inventario palancas / reflect: ApiExplorerMod F6/F7 ^(no F9^)
echo.
echo  Python: probe_ue4ss.bat  o  probe_ue4ss_log.bat
echo  IPC: %%TEMP%%\TSW6Bridge\GetData.txt
echo.
pause
