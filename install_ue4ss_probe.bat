@echo off
chcp 65001 >nul
title TSW6 - Instalar TelemetryProbeMod (UE4SS)

cd /d "%~dp0"

set "TSW_ROOT=C:\Program Files (x86)\Steam\steamapps\common\Train Sim World 6"
if not "%~1"=="" set "TSW_ROOT=%~1"

set "MODS_SRC=%~dp0mods\TelemetryProbeMod"
set "MODS_DST=%TSW_ROOT%\WindowsNoEditor\TS2Prototype\Binaries\Win64\Mods"
set "MODS_TXT=%MODS_DST%\mods.txt"

echo.
echo  TelemetryProbeMod - instalador UE4SS
echo  Origen:  %MODS_SRC%
echo  Destino: %MODS_DST%
echo.

if not exist "%MODS_SRC%\Scripts\main.lua" (
    echo [ERROR] No se encuentra mods\TelemetryProbeMod en el repo.
    pause
    exit /b 1
)

if not exist "%MODS_DST%" (
    echo [ERROR] No existe la carpeta Mods del juego.
    echo         ¿TSW6 + UE4SS instalados en:
    echo         %TSW_ROOT%
    pause
    exit /b 1
)

xcopy "%MODS_SRC%" "%MODS_DST%\TelemetryProbeMod\" /E /I /Y >nul
if errorlevel 1 (
    echo [ERROR] Fallo al copiar TelemetryProbeMod.
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
echo  Instalado. Reinicia TSW6 si estaba abierto.
echo.
echo  En cabina:
echo    F7  activar/desactivar probe
echo    F8  volcar linea al log + GetData.txt
echo.
echo  DynamicHUDMod : 0 en mods.txt y SIN Mods\DynamicHUDMod\enabled.txt
echo  ^(enabled.txt carga el mod aunque mods.txt diga : 0^).
echo.
echo  Autopiloto: ademas arranca TSW con -HTTPAPI para escribir mandos.
echo  Calibracion ^(aprender.bat^): solo probe, no hace falta HTTPAPI.
echo.
echo  Python (otra ventana):
echo    probe_ue4ss.bat
echo    probe_ue4ss_log.bat     ^(guarda logs\ue4ss_probe_*.txt^)
echo    o: python tsw_ue4ss_reader.py --benchmark 20
echo.
echo  Archivo IPC: %%TEMP%%\TSW6Bridge\GetData.txt
echo.
pause
