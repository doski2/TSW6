@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title TSW6 - Instalar TelemetryProbeMod (UE4SS)

cd /d "%~dp0..\.."
set "PYTHONPATH=%CD%"

set "TSW_ROOT=C:\Program Files (x86)\Steam\steamapps\common\Train Sim World 6"
if not "%~1"=="" set "TSW_ROOT=%~1"

set "MODS_SRC=%CD%\mods\TelemetryProbeMod"
set "MODS_DST=%TSW_ROOT%\WindowsNoEditor\TS2Prototype\Binaries\Win64\Mods"
set "MODS_TXT=%MODS_DST%\mods.txt"
set "LUA_SRC=%MODS_SRC%\Scripts\main.lua"
set "LUA_DST=%MODS_DST%\TelemetryProbeMod\Scripts\main.lua"
set "LUA_DIR=%MODS_DST%\TelemetryProbeMod\Scripts"

echo.
echo  TelemetryProbeMod - instalador UE4SS
echo  Repo:   "%MODS_SRC%"
echo  Juego:  "%MODS_DST%"
echo.

if not exist "%LUA_SRC%" (
    echo [ERROR] No se encuentra mods\TelemetryProbeMod\Scripts\main.lua en el repo.
    pause
    exit /b 1
)

if not exist "%MODS_DST%" (
    echo [ERROR] No existe la carpeta Mods del juego.
    echo         TSW6 + UE4SS esperados en:
    echo         "%TSW_ROOT%"
    echo.
    echo         Si TSW esta en otra ruta, arrastra este .bat sobre la carpeta
    echo         del juego o ejecuta:
    echo           install_ue4ss_probe.bat "RUTA\Train Sim World 6"
    pause
    exit /b 1
)

for %%A in ("%LUA_SRC%") do set "SRC_SIZE=%%~zA"
for %%A in ("%LUA_SRC%") do set "SRC_DATE=%%~tA"
echo  Repo main.lua: !SRC_SIZE! bytes  !SRC_DATE!

set "NEED_COPY=1"
if exist "%LUA_DST%" (
    for %%B in ("%LUA_DST%") do set "DST_SIZE=%%~zB"
    for %%B in ("%LUA_DST%") do set "DST_DATE=%%~tB"
    echo  Juego main.lua: !DST_SIZE! bytes  !DST_DATE!
    fc /b "%LUA_SRC%" "%LUA_DST%" >nul 2>&1
    if not errorlevel 1 (
        set "NEED_COPY=0"
        echo  Contenido: IDENTICO al repo ^(misma hora en ambos es normal^)
    ) else (
        echo  Contenido: DISTINTO — se actualizara
    )
) else (
    echo  Juego main.lua: no existe — se creara
)
echo.

if "!NEED_COPY!"=="1" (
    if not exist "%LUA_DIR%" mkdir "%LUA_DIR%"
    if not exist "%LUA_DIR%" (
        echo [ERROR] No se pudo crear "%LUA_DIR%"
        pause
        exit /b 1
    )
    copy /Y "%LUA_SRC%" "%LUA_DST%" >nul
    if errorlevel 1 (
        echo [ERROR] Fallo copy /Y — prueba ejecutar como Administrador
        echo         Origen:  "%LUA_SRC%"
        echo         Destino: "%LUA_DST%"
        pause
        exit /b 1
    )
    fc /b "%LUA_SRC%" "%LUA_DST%" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Tras copiar, main.lua sigue distinto al repo.
        echo         Comprueba permisos o antivirus en "%MODS_DST%"
        pause
        exit /b 1
    )
    echo  Copia OK ^(contenido verificado byte a byte^)
) else (
    rem Forzar copia aunque sea identico: asegura permisos y ruta correcta
    copy /Y "%LUA_SRC%" "%LUA_DST%" >nul
    if errorlevel 1 (
        echo [ERROR] No se pudo escribir en "%LUA_DST%"
        pause
        exit /b 1
    )
)

findstr /C:"PROBE_BUILD" "%LUA_DST%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] main.lua del juego sin PROBE_BUILD — copia incompleta o mod viejo.
    pause
    exit /b 1
)
echo  Version en juego:
findstr /C:"PROBE_BUILD" "%LUA_DST%"
echo  Version en repo:
findstr /C:"PROBE_BUILD" "%LUA_SRC%"

findstr /C:"lever_notch=" "%LUA_DST%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] main.lua sin lever_notch — mod demasiado antiguo.
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

for %%B in ("%LUA_DST%") do set "DST_SIZE=%%~zB"
for %%B in ("%LUA_DST%") do set "DST_DATE=%%~tB"
if not "!SRC_SIZE!"=="!DST_SIZE!" (
    echo [ERROR] Tamano distinto tras instalar ^(!SRC_SIZE! vs !DST_SIZE!^).
    pause
    exit /b 1
)

echo.
echo  [OK] TelemetryProbeMod instalado
echo       !DST_SIZE! bytes  !DST_DATE!
echo       Si la fecha es igual que el repo, la instalacion es correcta.
echo       Reinicia TSW6 si estaba abierto ^(UE4SS no recarga Lua en caliente^).
echo.
echo  En cabina:
echo    Probe AUTO-START al cargar escenario ^(F7 apaga si juegas sin autopilot^)
echo    F8  volcar linea al log + GetData.txt
echo.
echo  DynamicHUDMod : 0 en mods.txt y SIN Mods\DynamicHUDMod\enabled.txt
echo  ^(enabled.txt carga el mod aunque mods.txt diga : 0^).
echo.
echo  Autopiloto: UE4SS probe ^(mandos SendCommand.txt^). -HTTPAPI solo para planning 2 limites.
echo  Calibracion ^(aprender.bat^): solo probe, no hace falta HTTPAPI.
echo.
echo  Python ^(otra ventana^):
echo    probe_ue4ss.bat
echo    probe_ue4ss_log.bat     ^(guarda logs\ue4ss_probe_*.txt^)
echo    o: python tsw_ue4ss_reader.py --benchmark 20
echo.
echo  Archivo IPC: %%TEMP%%\TSW6Bridge\GetData.txt
echo  Tras entrar en cabina GetData.txt debe actualizarse ^(seq, speed_ms, lever_notch^)
echo.
pause
