@echo off
title TSW6 Monitor
echo.
echo  ╔══════════════════════════════════════╗
echo  ║       TSW6 API Monitor               ║
echo  ║  Asegurate de tener TSW corriendo    ║
echo  ║  con la opcion -HTTPAPI en Steam     ║
echo  ╚══════════════════════════════════════╝
echo.

:: Instalar dependencias si faltan
python -c "import requests, colorama" 2>nul
if errorlevel 1 (
    echo  Instalando dependencias...
    pip install requests colorama
    echo.
)

:: Menu
echo  Modos disponibles:
echo    1. monitor   - Dashboard visual en tiempo real (defecto)
echo    2. discover  - Ver todos los endpoints y sus datos
echo    3. snapshot  - Guardar captura JSON en este momento
echo    4. raw       - JSON crudo continuo
echo.
set /p MODO=" Elige modo (Enter = monitor): "
if "%MODO%"=="" set MODO=monitor

python tsw_monitor.py %MODO%
pause
