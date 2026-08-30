@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title TSW6 - Instalar ApiExplorerMod (UE4SS lab)

cd /d "%~dp0..\.."
if not exist "%CD%\mods\ApiExplorerMod\Scripts\main.lua" (
    echo.
    echo [ERROR] No se encuentra mods\ApiExplorerMod\Scripts\main.lua
    echo.
    echo  Repo esperado: "%CD%"
    echo.
    echo  Ejecuta desde la raiz del repo TSW6:
    echo    install_ue4ss_explorer.bat
    echo.
    pause
    exit /b 1
)

set "PYTHONPATH=%CD%"

set "TSW_ROOT=C:\Program Files (x86)\Steam\steamapps\common\Train Sim World 6"
if not "%~1"=="" set "TSW_ROOT=%~1"

set "MODS_SRC=%CD%\mods\ApiExplorerMod\Scripts"
set "MODS_DST=%TSW_ROOT%\WindowsNoEditor\TS2Prototype\Binaries\Win64\Mods"
set "MODS_TXT=%MODS_DST%\mods.txt"
set "LUA_DST=%MODS_DST%\ApiExplorerMod\Scripts"

echo.
echo  ApiExplorerMod - instalador UE4SS (laboratorio)
echo  Repo:   "%CD%"
echo  Lua:    "%MODS_SRC%"
echo  Juego:  "%LUA_DST%"
echo.

if not exist "%MODS_DST%" (
    echo [ERROR] No existe la carpeta Mods del juego.
    echo         "%TSW_ROOT%"
    echo.
    echo         install_ue4ss_explorer.bat "RUTA\Train Sim World 6"
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

findstr /C:"ApiExplorer" "%LUA_DST%\main.lua" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] main.lua del juego invalido.
    pause
    exit /b 1
)

findstr /I /C:"ApiExplorerMod" "%MODS_TXT%" >nul 2>&1
if errorlevel 1 (
    echo ApiExplorerMod : 1 >> "%MODS_TXT%"
    echo  Anadido ApiExplorerMod : 1 en mods.txt
) else (
    echo  ApiExplorerMod ya estaba en mods.txt
)

set "LAB_EXPORTS=%CD%\data\lab_exports"
if not exist "%LAB_EXPORTS%" mkdir "%LAB_EXPORTS%"
if not exist "%LAB_EXPORTS%\exports" mkdir "%LAB_EXPORTS%\exports"

set "DOC_TSW6=%USERPROFILE%\Documents\TSW6"
if not exist "%DOC_TSW6%" mkdir "%DOC_TSW6%"
(echo %LAB_EXPORTS%)> "%DOC_TSW6%\lab_root.txt"

if not exist "%TEMP%\TSW6Lab" mkdir "%TEMP%\TSW6Lab"
(echo %LAB_EXPORTS%)> "%TEMP%\TSW6Lab\lab_root.txt"

echo.
echo  Exports JSON: %LAB_EXPORTS%\exports\
echo  (puntero: %%USERPROFILE%%\Documents\TSW6\lab_root.txt)
echo.
echo  [OK] ApiExplorerMod instalado
echo       Reinicia TSW6 si estaba abierto.
echo.
echo  NO hay menu en pantalla. En CABINA:
echo    F5 hud_batch  F6 controls  F7 driver_aid
echo    (F10 = consola UE4SS si ConsoleEnablerMod : 1)
echo.
echo  UE4SS.log debe mostrar: [ApiExplorer] Mod loaded
echo.
echo  Solo laboratorio: ApiExplorerMod : 1  TelemetryProbeMod : 0
echo.
pause
