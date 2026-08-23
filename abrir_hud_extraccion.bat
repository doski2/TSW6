@echo off
chcp 65001 >nul
title TSW HUD - Extraccion de horarios
setlocal

set "HUD_ROOT=%USERPROFILE%\Desktop\investigacion tsw 6\tsw_projects-main\tsw_projects-main\hud"
set "HUD_EXE=%HUD_ROOT%\src-tauri\target\release\hud.exe"
set "DB_FILE=%HUD_ROOT%\resources\db\tsw_hud.db"
set "TSW_ROOT=C:\Program Files (x86)\Steam\steamapps\common\Train Sim World 6"

if not exist "%HUD_EXE%" (
    echo  hud.exe no compilado. Ejecuta primero: extraer_horario_hud.bat
    pause & exit /b 1
)

if not exist "%DB_FILE%" (
    echo.
    echo  ============================================================
    echo   FALTA tsw_hud.db  —  el HUD no puede buscar ni extraer
    echo  ============================================================
    echo.
    echo  La carpeta existe pero esta vacia:
    echo    %DB_FILE%
    echo.
    echo  GitHub NO incluye esta BD. Hay que copiarla del mod oficial
    echo  (~770 MB): 2-July-2026-hud-rust.zip
    echo.
    echo  Ejecutando preparar_db_hud.bat para guiarte...
    echo.
    call "%~dp0preparar_db_hud.bat"
    if not exist "%DB_FILE%" exit /b 1
)

echo  Abriendo TSW HUD...
echo  En la app: Extraction ^> TSW path = %TSW_ROOT%
echo  Luego: Load my DLCs
start "" "%HUD_EXE%"
