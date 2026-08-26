@echo off
cd /d "%~dp0"
echo TSW6 — Control latency probe (F7 probe ON, en cabina)
python -m tsw6.telemetry.control_latency_probe %*
pause
