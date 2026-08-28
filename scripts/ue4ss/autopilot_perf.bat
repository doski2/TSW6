@echo off
chcp 65001 >nul
title TSW6 - Rendimiento autopilot (CPU / work)

cd /d "%~dp0..\.."
set "PYTHONPATH=%CD%"

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    for %%c in (python3 python py) do (
        if not defined PY (
            %%c --version >nul 2>&1 && set "PY=%%c"
        )
    )
)
if not defined PY (
    echo [ERROR] Python no encontrado.
    pause
    exit /b 1
)

echo Analizando el log de autopilot mas reciente (o el que indiques)...
echo.
"%PY%" -m tsw6.telemetry.autopilot_perf %*
set "ERR=%ERRORLEVEL%"
echo.
if "%ERR%"=="0" (
    echo Resultado: OK
) else if "%ERR%"=="2" (
    echo Resultado: no hay log
) else (
    echo Resultado: FALLA regimen
)
echo.
pause
exit /b %ERR%
