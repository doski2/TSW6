@echo off
chcp 65001 >nul
title TSW6 - Monitor UE4SS probe

cd /d "%~dp0"

set "PY="
for %%c in (python3 python py) do (
    if not defined PY (
        %%c --version >nul 2>&1 && set "PY=%%c"
    )
)
if not defined PY (
    echo [ERROR] Python no encontrado.
    pause
    exit /b 1
)

%PY% -c "import colorama" >nul 2>&1 || %PY% -m pip install --quiet colorama
%PY% tsw_ue4ss_reader.py %*
