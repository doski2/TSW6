@echo off
REM Launcher V2 — doble clic = menu; desde cmd: V2\run.bat console ...
cd /d "%~dp0.."
set "PYTHONPATH=%CD%;%CD%\V2"
set "PYTHONIOENCODING=utf-8"

if "%~1"=="" goto menu
if /I "%~1"=="-h" goto menu
if /I "%~1"=="--help" goto menu
if /I "%~1"=="help" goto menu

python -m tsw6v2 %*
set "ERR=%ERRORLEVEL%"
if %ERR% NEQ 0 (
    echo.
    echo [FAIL] codigo %ERR%
    pause
)
exit /b %ERR%

:menu
echo.
echo === TSW6 V2 ===
echo.
echo   1  Sesion cartel P1 + log + HTML  ^(cross-city^)
echo   2  Consola limit + investigate    ^(sin log^)
echo   3  Consola limit + log + HTML     ^(ruta manual^)
echo   4  Solo probe 15 s               ^(sin P1^)
echo   5  test-ipc
echo   6  gui
echo   7  Ayuda CLI completa
echo   0  Salir
echo.
echo Desde cmd: V2\run.bat console --mode limit --investigate --log --route cross-city
echo.
set /p "CH=Opcion [0-7]: "
if "%CH%"=="0" exit /b 0
if "%CH%"=="1" (
    call "%~dp0run_p1_session.bat" limit cross-city
    exit /b %ERRORLEVEL%
)
if "%CH%"=="2" (
    python -m tsw6v2 console --mode limit --investigate
    goto done
)
if "%CH%"=="3" goto opt3_log
if "%CH%"=="4" (
    python -m tsw6v2 console --duration 15
    goto done
)
if "%CH%"=="5" (
    call "%~dp0test_ipc.bat"
    exit /b %ERRORLEVEL%
)
if "%CH%"=="6" (
    python -m tsw6v2 gui
    goto done
)
if "%CH%"=="7" (
    python -m tsw6v2 --help
    echo.
    python -m tsw6v2 console --help
    goto done
)
echo Opcion no valida.
goto done

:opt3_log
set "ROUTE=session"
set /p "ROUTE=Etiqueta ruta (ej. cross-city): "
if "%ROUTE%"=="" set "ROUTE=session"
python -m tsw6v2 console --mode limit --investigate --log --open-html --route %ROUTE%
goto done
:done
echo.
pause
exit /b 0
