@echo off
REM Tabla + amps_report.md para sesion ApiExplorer (fase 2 plan amps/puertas).
REM Uso: summarizar_amps_lab.bat SESSION_ID
REM   SESSION_ID = carpeta bajo data\lab_exports\exports\ (ej. 20261007T120000Z)
cd /d "%~dp0"
set "PYTHONPATH=%CD%"

set "PY="
if exist "%CD%\.venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
if not defined PY (
    for %%c in (py python) do (
        if not defined PY %%c -3 --version >nul 2>&1 && set "PY=%%c -3"
    )
)
if not defined PY set "PY=python"

if "%~1"=="" (
    echo.
    echo  Uso: summarizar_amps_lab.bat SESSION_ID
    echo  Ej:  summarizar_amps_lab.bat 20261007T120000Z
    echo.
    echo  Carpeta: data\lab_exports\exports\^<SESSION_ID^>\hud_batch_*.json
    echo.
    pause
    exit /b 1
)

set "SESS=data\lab_exports\exports\%~1"
if not exist "%SESS%" (
    echo [ERROR] No existe: %SESS%
    pause
    exit /b 1
)

"%PY%" scripts\tools\summarize_hud_amps.py "%SESS%" --write-report
set "ERR=%ERRORLEVEL%"
echo.
if %ERR% EQU 0 (
    echo [OK] Veredicto variable — revisar amps_report.md y cruzar con probe fase 1
) else if %ERR% EQU 2 (
    echo [AVISO] Sin amps utiles — repite F5 reposo + traccion M3a
) else (
    echo [FAIL] codigo %ERR%
)
pause
exit /b %ERR%
