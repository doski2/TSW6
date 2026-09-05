@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title TSW6 - Monitor UE4SS probe

cd /d "%~dp0..\.."
set "PYTHONPATH=%CD%"

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    for %%c in (py python) do (
        if not defined PY (
            %%c -3 --version >nul 2>&1 && set "PY=%%c -3"
        )
    )
)
if not defined PY (
    for %%c in (python) do (
        if not defined PY (
            %%c --version >nul 2>&1 && set "PY=%%c"
        )
    )
)
if not defined PY (
    echo.
    echo  [ERROR] Python no encontrado.
    echo  Instala Python 3.9+ o crea .venv en el repo.
    echo.
    pause
    exit /b 1
)

set "BRIDGE=%TEMP%\TSW6Bridge\GetData.txt"
echo.
echo  TSW6 probe monitor
echo  Repo:    %CD%
echo  GetData: %BRIDGE%
echo.

if not exist "%TEMP%\TSW6Bridge" (
    echo  [AVISO] No existe %%TEMP%%\TSW6Bridge\
    echo          Arranca TSW6, install_ue4ss_probe.bat, entra en cabina.
    echo.
)

%PY% -c "import colorama" >nul 2>&1
if errorlevel 1 (
    echo  Instalando colorama...
    %PY% -m pip install --quiet colorama
)

rem Modo simple por defecto (sin ANSI). Pasa --benchmark N o quita --simple si quieres pantalla fija.
if "%~1"=="" (
    %PY% -m tsw6.telemetry.tsw_ue4ss_reader --simple
) else (
    %PY% -m tsw6.telemetry.tsw_ue4ss_reader %*
)

set "ERR=!ERRORLEVEL!"
if not "!ERR!"=="0" (
    echo.
    echo  [ERROR] Salida codigo !ERR!
    pause
    exit /b !ERR!
)
