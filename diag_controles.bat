@echo off
chcp 65001 >nul
title TSW6 Diagnostico de Mandos (Fase 0)

cd /d "%~dp0"

set "PY="
for %%c in (python3 python py) do (
    if not defined PY (
        %%c --version >nul 2>&1 && (
            for /f "tokens=2" %%v in ('%%c --version 2^>^&1') do (
                for /f "tokens=1,2 delims=." %%a in ("%%v") do (
                    if %%a geq 3 if %%b geq 9 set "PY=%%c"
                )
            )
        )
    )
)
if not defined PY (
    echo ERROR: Python 3.9+ no encontrado.
    pause
    exit /b 1
)

cls
echo.
echo  ════════════════════════════════════════════════════════════
echo    FASE 0 — DIAGNOSTICO DE MANDOS
echo  ════════════════════════════════════════════════════════════
echo.
echo    Recorre las muescas del tren (un mando a la vez).
echo    Al terminar guarda:
echo      · logs/control_diag_*.txt          (resumen)
echo      · logs/control_schemas/^<Tren^>.json  (muescas para aprender)
echo.
echo    1. Arranca TSW6 y RailBridge (boton CMP)
echo    2. Sube al tren que quieras calibrar despues
echo    3. Mueve UN mando a la vez por todo su rango
echo    4. Ctrl+C — luego usa aprender.bat con el mismo tren
echo.
pause

%PY% control_diag.py --save

echo.
pause
