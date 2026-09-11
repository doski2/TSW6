@echo off
REM GUI V2 en monitor secundario maximizado (juego en primario).
REM Monitor primario: set TSW6_GUI_SECONDARY=0 antes de ejecutar.
cd /d "%~dp0.."
set "PYTHONPATH=%CD%;%CD%\V2"
set "TSW6_GUI_SECONDARY=1"
python -m tsw6v2 gui %*
set "ERR=%ERRORLEVEL%"
if %ERR% NEQ 0 pause
exit /b %ERR%
