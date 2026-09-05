@echo off
cd /d "%~dp0.."
set "PYTHONPATH=%CD%;%CD%\V2"
set "PYTHONIOENCODING=utf-8"
python -m tsw6v2 test-ipc %*
set "ERR=%ERRORLEVEL%"
echo.
if %ERR% NEQ 0 (echo [FAIL] codigo %ERR%) else (echo [OK] test-ipc terminado)
pause
exit /b %ERR%
