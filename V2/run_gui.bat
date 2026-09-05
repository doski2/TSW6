@echo off
cd /d "%~dp0.."
set "PYTHONPATH=%CD%;%CD%\V2"
python -m tsw6v2 gui %*
