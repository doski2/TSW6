@echo off
chcp 65001 >nul
title Preparar tsw_hud.db para extraccion
setlocal EnableDelayedExpansion

set "HUD_ROOT=%USERPROFILE%\Desktop\investigacion tsw 6\tsw_projects-main\tsw_projects-main\hud"
set "DB_DIR=%HUD_ROOT%\resources\db"
set "DB_FILE=%DB_DIR%\tsw_hud.db"
set "DB_RELEASE=%HUD_ROOT%\src-tauri\target\release\resources\db\tsw_hud.db"
set "MOD_ZIP="

echo.
echo  ============================================================
echo   PREPARAR tsw_hud.db  (base de datos semilla del HUD)
echo  ============================================================
echo.

if not exist "%DB_DIR%" mkdir "%DB_DIR%"
if not exist "%HUD_ROOT%\src-tauri\target\release\resources\db" (
    mkdir "%HUD_ROOT%\src-tauri\target\release\resources\db"
)

if exist "%DB_FILE%" (
    for %%A in ("%DB_FILE%") do set "SZ=%%~zA"
    echo  [OK] Ya existe: %DB_FILE%  (!SZ! bytes^)
    goto verify
)

echo  [FALTA] No hay tsw_hud.db en:
echo          %DB_FILE%
echo.
echo  El codigo fuente de GitHub NO incluye esta BD (esta en .gitignore).
echo  Viene en el mod oficial de Train Sim Community (~770 MB).
echo.
echo  PASOS:
echo    1. Descarga el mod "TSW HUD ^& Timetable Extractor" v4.0.2
echo       https://www.trainsimcommunity.com/mods/c3-train-sim-world/c75-utilities/i7169-tsw-hud-timetable-extractor
echo       Archivo: 2-July-2026-hud-rust.zip
echo    2. Descomprime el ZIP
echo    3. Busca dentro:  hud\resources\db\tsw_hud.db
echo    4. Copialo a:
echo       %DB_FILE%
echo.

set /p "MOD_ZIP=Ruta al ZIP descargado (Enter para omitir): "
if "%MOD_ZIP%"=="" goto manual

if not exist "%MOD_ZIP%" (
    echo  No encuentro ese archivo.
    goto manual
)

echo  Buscando tsw_hud.db dentro del ZIP...
powershell -NoProfile -Command ^
  "$z='%MOD_ZIP%'; $dest='%DB_FILE%'; Add-Type -AssemblyName System.IO.Compression.FileSystem; $a=[IO.Compression.ZipFile]::OpenRead($z); $e=$a.Entries | Where-Object { $_.FullName -match 'tsw_hud\.db$' } | Select-Object -First 1; if(-not $e){ Write-Host 'NO_ENCONTRADO'; exit 1 }; [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dest)) | Out-Null; [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dest, $true); Write-Host ('OK ' + (Get-Item $dest).Length)"

if errorlevel 1 goto manual
goto verify

:manual
echo.
echo  Cuando hayas copiado tsw_hud.db manualmente, pulsa una tecla...
pause >nul

:verify
if not exist "%DB_FILE%" (
    echo.
    echo  [ERROR] Sigue sin existir tsw_hud.db
    pause & exit /b 1
)

echo.
echo  Copiando a las rutas que usa hud.exe y el autopilot...
copy /Y "%DB_FILE%" "%DB_RELEASE%" >nul
copy /Y "%DB_FILE%" "%~dp0tsw_hud.db" >nul
echo    [OK] %DB_FILE%
echo    [OK] %DB_RELEASE%
echo    [OK] %~dp0tsw_hud.db
cd /d "%~dp0"
python verificar_hud_db.py
echo.
echo  Ahora en hud.exe: Extraction -^> Load my DLCs
echo  (marca "Re-extract" si quieres repetir rutas que fallaron)
pause
