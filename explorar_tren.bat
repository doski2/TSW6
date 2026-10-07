@echo off
chcp 65001 >nul
title TSW6 Vehicle Lab
cd /d "%~dp0"
set "PYTHONPATH=%CD%"
set "PYTHONIOENCODING=utf-8"

set "PY="
if exist "%CD%\.venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
if not defined PY (
    for %%c in (py python python3) do (
        if not defined PY (
            %%c -3 --version >nul 2>&1 && set "PY=%%c -3"
        )
    )
)
if not defined PY (
    for %%c in (python) do (
        if not defined PY %%c --version >nul 2>&1 && set "PY=%%c"
    )
)
if not defined PY (
    echo [ERROR] Python no encontrado
    pause
    exit /b 1
)

echo.
echo  Vehicle Lab - sesiones en data\lab_exports\exports\
echo  En juego: install_ue4ss_explorer.bat luego F5 F6 F7
echo  Doc: docs\v2\VEHICLE_LAB.md
echo.

if /I "%~1"=="--list" (
    "%PY%" -m lab.vehicle_explorer --list
    pause
    exit /b 0
)

"%PY%" -m lab.vehicle_explorer %*
set "ERR=%ERRORLEVEL%"
echo.
if %ERR% NEQ 0 (echo [FAIL] codigo %ERR%) else (echo [OK] Vehicle Lab)
pause
exit /b %ERR%
