@echo off
REM Comparar dos sesiones JSONL + abrir replays HTML.
REM Uso: V2\compare_sessions.bat [jsonl_A] [jsonl_B]
cd /d "%~dp0.."
set "PYTHONPATH=%CD%;%CD%\V2"
set "PYTHONIOENCODING=utf-8"

set "A=logs\v2\20260903T185740Z_cross-city_limit.jsonl"
set "B=logs\v2\20260903T222538Z_cross-city_limit.jsonl"
if not "%~1"=="" set "A=%~1"
if not "%~2"=="" set "B=%~2"

if not exist "%A%" (
    echo [FAIL] No existe: %A%
    pause
    exit /b 1
)
if not exist "%B%" (
    echo [FAIL] No existe: %B%
    pause
    exit /b 1
)

python scripts\tools\compare_v2_sessions.py "%A%" "%B%" --html --open
set "ERR=%ERRORLEVEL%"
echo.
if %ERR% NEQ 0 (
    echo [FAIL] codigo %ERR%
) else (
    echo [OK] Comparacion lista — dos pestanas HTML
)
pause
exit /b %ERR%
