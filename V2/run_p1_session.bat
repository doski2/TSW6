@echo off
REM Sesion P1 con trace JSONL + investigate (cartel, estacion, senal).
REM Uso: V2\run_p1_session.bat MODE [ROUTE] [-- extras para tsw6v2 ...]
REM   MODE:  limit ^| station ^| signal ^| p1
REM   ROUTE: etiqueta en logs (ej. cross-city, four-oaks)
cd /d "%~dp0.."
set "PYTHONPATH=%CD%;%CD%\V2"
set "PYTHONIOENCODING=utf-8"

if "%~1"=="" goto usage
if /I "%~1"=="-h" goto usage
if /I "%~1"=="--help" goto usage
if /I "%~1"=="help" goto usage

set "MODE=%~1"
set "ROUTE=%~2"
if "%ROUTE%"=="" set "ROUTE=session"

REM %* no cambia tras shift en cmd — extras desde %3
python -m tsw6v2 console --mode %MODE% --investigate --log --open-html --route %ROUTE% %3 %4 %5 %6 %7 %8 %9
set "ERR=%ERRORLEVEL%"
echo.
if %ERR% NEQ 0 (
    echo [FAIL] codigo %ERR%
) else (
    echo [OK] Sesion cerrada — JSONL + replay HTML en logs\v2\
    echo      HTML solo si ^>=15 ticks y ^>=5s; navegador si ^>=40 ticks y ^>=12s
    echo      Concepto capas: docs\v2\p1_limit_capas.html
)
pause
exit /b %ERR%

:usage
echo.
echo V2\run_p1_session.bat MODE [ROUTE] [-- opciones extra]
echo.
echo   MODE   limit    carteles P1 ^(paso 3, activo^)
echo          station  anden ^(paso 7 — trace hasta cablear P1^)
echo          signal   semaforo ^(paso 4-5 — trace hasta cablear P1^)
echo          p1       todo P1 cuando exista
echo   ROUTE  etiqueta en nombre de log ^(default: session^)
echo.
echo Ejemplos:
echo   V2\run_p1_session.bat limit cross-city
echo   V2\run_p1_session.bat signal four-oaks
echo   V2\run_p1_session.bat limit cross-city -- --duration 120
echo.
exit /b 1
