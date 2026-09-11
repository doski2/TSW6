@echo off
REM Consola P1 en monitor SECUNDARIO maximizado (solo sesiones limit/station).
REM Para GUI: usar V2\run_gui.bat directamente (coloca la ventana tk, no esta consola).
REM   run_git.bat limit cross-city
REM   run_git.bat station cross-city
cd /d "%~dp0"

if "%TSW6_SECONDARY_LAUNCH%"=="1" goto :run

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\win\launch_on_secondary.ps1" "%~f0" %*
if errorlevel 1 (
    echo.
    echo [ERROR] No se pudo abrir en monitor secundario.
    pause
    exit /b 1
)
exit /b 0

:run
if "%~1"=="" goto :usage
if /I "%~1"=="-h" goto :usage
if /I "%~1"=="--help" goto :usage
if /I "%~1"=="help" goto :usage

call "%~dp0V2\run_p1_session.bat" %*
exit /b %ERRORLEVEL%

:usage
echo.
echo run_git.bat MODE [ROUTE]   ^(consola P1 en monitor secundario^)
echo.
echo   limit cross-city     sesion cartel P1
echo   station cross-city   sesion anden P1
echo.
echo GUI:  V2\run_gui.bat
echo.
echo Ejemplo: run_git.bat limit cross-city
echo.
pause
exit /b 1
