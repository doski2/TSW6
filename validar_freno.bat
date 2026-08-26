@echo off

chcp 65001 >nul

title TSW6 Laboratorio frenos



cd /d "%~dp0"

set "PYTHONPATH=%CD%"



set "PY="

if exist ".venv\Scripts\python.exe" (

    set "PY=.venv\Scripts\python.exe"

    goto py_ok

)

for %%c in (python3 python py) do (

    if not defined PY (

        %%c --version >nul 2>&1 && set "PY=%%c"

    )

)

:py_ok

if not defined PY (

    echo.

    echo  [ERROR] No se encontro Python.

    echo.

    pause

    exit /b 1

)



"%PY%" -c "import requests" >nul 2>&1

if errorlevel 1 (

    "%PY%" -m pip install --quiet requests

)



:menu

cls

echo.

echo  ============================================================

echo    TSW6 - LABORATORIO DE FRENOS

echo  ============================================================

echo.

echo    Lua probe + HTTPAPI - CSV en logs\brake_physics\

echo.

echo    1. GUI laboratorio (recomendado)

echo    2. Consola guiada (fases)

echo    3. Grabacion libre 30 s

echo    4. Informe ultimo CSV

echo    5. Salir

echo.

set /p "OP=  Opcion [1]: "

if "%OP%"=="" set "OP=1"



if "%OP%"=="1" goto gui

if "%OP%"=="2" goto consola

if "%OP%"=="3" goto libre30

if "%OP%"=="4" goto review

if "%OP%"=="5" exit /b 0

goto menu



:gui

"%PY%" -m tsw6.learning.brake_physics_monitor --gui

goto fin



:consola

"%PY%" -m tsw6.learning.brake_physics_monitor --console

goto fin



:libre30

"%PY%" -m tsw6.learning.brake_physics_monitor --console --free 30

goto fin



:review

"%PY%" -m tsw6.learning.brake_physics_monitor --review logs\brake_physics\latest.csv

goto fin



:fin

echo.

pause

exit /b 0

