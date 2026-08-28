@echo off
chcp 65001 >nul
title TSW6 - Rendimiento probe Lua (UE4SS.log)

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

echo Analizando UE4SS.log del probe Lua...
echo.
"%PY%" -m tsw6.telemetry.lua_probe_perf %*
set "ERR=%ERRORLEVEL%"
echo.
if "%ERR%"=="0" (
    echo Resultado: OK
) else if "%ERR%"=="2" (
    echo Resultado: no hay log
) else (
    echo Resultado: FALLA regimen (Hz / avg_ms)
)
echo.
pause
exit /b %ERR%
