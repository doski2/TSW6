@echo off
REM Sesion P1 con trace JSONL + investigate (cartel, estacion, senal).
REM Uso: V2\run_p1_session.bat MODE [ROUTE] [-- extras para tsw6v2 ...]
REM   MODE:  trace ^| limit ^| station ^| signal ^| p1
REM   trace = solo telemetria JSONL (amps/puertas); sin P1 ni mandos
REM   ROUTE: etiqueta en logs (ej. gct-mnr, cross-city)
setlocal EnableDelayedExpansion
cd /d "%~dp0.."
set "PYTHONPATH=%CD%;%CD%\V2"
set "PYTHONIOENCODING=utf-8"

set "PY="
if exist "%CD%\.venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
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
    echo [ERROR] Python no encontrado.
    echo   Crea .venv en la raiz del repo o instala Python 3.9+
    echo.
    pause
    exit /b 1
)

if "%~1"=="" goto usage
if /I "%~1"=="-h" goto usage
if /I "%~1"=="--help" goto usage
if /I "%~1"=="help" goto usage

set "MODE=%~1"
set "ROUTE=%~2"
if "%ROUTE%"=="" set "ROUTE=session"

if /I "%MODE%"=="trace" (
    echo [trace] JSONL probe-only — TSW en cabina, probe ON, Ctrl+C para guardar log
    echo         No usa P1 ni -HTTPAPI ^(plan amps/puertas^)
    "%PY%" -m tsw6v2 console --investigate --log --route %ROUTE% %3 %4 %5 %6 %7 %8 %9
    goto finish
)

REM %* no cambia tras shift en cmd — extras desde %3
"%PY%" -m tsw6v2 console --mode %MODE% --investigate --log --open-html --route %ROUTE% %3 %4 %5 %6 %7 %8 %9
goto finish

:finish
set "ERR=%ERRORLEVEL%"
echo.
if %ERR% NEQ 0 (
    echo [FAIL] codigo %ERR%
) else if /I "%MODE%"=="trace" (
    echo [OK] JSONL en logs\v2\ ^(*_probe-only.jsonl^) — Ctrl+C ya guardo el archivo
) else (
    echo [OK] Sesion cerrada — JSONL + replay HTML en logs\v2\
    echo      HTML solo si ^>=15 ticks y ^>=5s; navegador si ^>=40 ticks y ^>=12s
    echo      Concepto capas: docs\v2\p1_limit_capas.html
    echo      Perfil frenado: logs\profiles\^<vehiculo^>.json si existe ^(auto^)
)
pause
exit /b %ERR%

:usage
echo.
echo V2\run_p1_session.bat MODE [ROUTE] [-- opciones extra]
echo.
echo   MODE   trace    solo JSONL telemetria ^(amps, doors_telem^) — recomendado plan puertas/amps
echo          limit    carteles P1 ^(paso 3, activo^)
echo          station  anden P1 ^(Planning.txt; validacion paso 3; TSW -HTTPAPI^)
echo          signal   semaforo ^(paso 4-5 — trace hasta cablear P1^)
echo          p1       todo P1 cuando exista
echo   ROUTE  etiqueta en nombre de log ^(default: session^)
echo.
echo Ejemplos:
echo   V2\run_p1_session.bat trace gct-mnr
echo   V2\run_p1_session.bat limit cross-city
echo   V2\run_p1_session.bat station gct-mnr
echo   V2\run_p1_session.bat trace gct-mnr --duration 120
echo.
exit /b 1
