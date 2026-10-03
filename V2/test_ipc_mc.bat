@echo off
cd /d "%~dp0.."
set "PYTHONPATH=%CD%;%CD%\V2"
set "PYTHONIOENCODING=utf-8"
python -m tsw6v2.diagnostic_mc_ipc %*
pause
