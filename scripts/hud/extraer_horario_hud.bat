@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Extraer horarios TSW → tsw_hud.db
cd /d "%~dp0..\.."
set "PYTHONPATH=%CD%"

set "HUD_ROOT=%USERPROFILE%\Desktop\investigacion tsw 6\tsw_projects-main\tsw_projects-main\hud"
set "TSW_ROOT=C:\Program Files (x86)\Steam\steamapps\common\Train Sim World 6"
set "HUD_EXE=%HUD_ROOT%\src-tauri\target\release\hud.exe"
set "HUD_EXE_DBG=%HUD_ROOT%\src-tauri\target\debug\hud.exe"

echo.
echo  ============================================================
echo   EXTRAER HORARIOS TSW  (proyecto HUD → tsw_hud.db)
echo  ============================================================
echo.

:: ── 1. Python (verificador) ────────────────────────────────────────────────
set "PY="
for %%c in (python python3 py) do (
    if not defined PY %%c --version >nul 2>&1 && set "PY=%%c"
)
if not defined PY (
    echo  [ERROR] Python no encontrado.
    pause & exit /b 1
)

:: ── 2. Carpeta HUD ───────────────────────────────────────────────────────
if not exist "%HUD_ROOT%\src-tauri\Cargo.toml" (
    echo  [ERROR] No encuentro el proyecto HUD en:
    echo    %HUD_ROOT%
    pause & exit /b 1
)
echo  [OK] Proyecto HUD: %HUD_ROOT%

:: ── 3. TSW6 instalado ────────────────────────────────────────────────────
if not exist "%TSW_ROOT%\TS2Prototype.exe" (
    echo  [AVISO] TSW6 no en la ruta Steam por defecto.
    echo          Ajusta TSW_ROOT en este .bat o pon la ruta en hud.exe.
    set "TSW_OK=0"
) else (
    echo  [OK] TSW6: %TSW_ROOT%
    set "TSW_OK=1"
)

:: ── 4. Rust / cargo ────────────────────────────────────────────────────────
where cargo >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [PENDIENTE] Rust no instalado. Opciones:
    echo    A^) Ejecuta:  instalar_rust_hud.bat
    echo    B^) Manual:   https://rustup.rs  ^(instala Rust stable^)
    echo.
    set /p inst="  ¿Instalar Rust ahora con winget? (S/N): "
    if /i "!inst!"=="S" call "%~dp0instalar_rust_hud.bat"
    where cargo >nul 2>&1
    if errorlevel 1 (
        echo  Instala Rust y vuelve a ejecutar este script.
        pause & exit /b 1
    )
) else (
    for /f "delims=" %%v in ('cargo --version') do echo  [OK] %%v
)

:: ── 5. Compilar hud.exe si falta ─────────────────────────────────────────
if exist "%HUD_EXE%" (
    echo  [OK] hud.exe release ya compilado
    set "RUN_HUD=%HUD_EXE%"
) else if exist "%HUD_EXE_DBG%" (
    echo  [OK] hud.exe debug ya compilado
    set "RUN_HUD=%HUD_EXE_DBG%"
) else (
    echo.
    echo  Compilando hud.exe ^(primera vez ~2-5 min^)...
    pushd "%HUD_ROOT%"
    set "CARGO_TARGET_DIR=%HUD_ROOT%\src-tauri\target"
    cargo build --release --manifest-path src-tauri\Cargo.toml
    if errorlevel 1 (
        echo  [ERROR] Fallo la compilacion. Revisa errores arriba.
        popd
        pause & exit /b 1
    )
    popd
    set "RUN_HUD=%HUD_EXE%"
    echo  [OK] Compilado: %RUN_HUD%
)

:: ── 6. repak.exe ─────────────────────────────────────────────────────────
if exist "%HUD_ROOT%\resources\repak.exe" (
    echo  [OK] repak.exe en resources\
) else (
    echo.
    echo  [AVISO] Falta repak.exe para desempaquetar paks de TSW.
    echo          En hud.exe ^> Extraction te dira donde ponerlo.
    echo          Suele ir en: %HUD_ROOT%\resources\repak.exe
    echo          Descarga desde el repo repak ^(releases^) si hace falta.
)

:: ── 7. Ya hay BD? ────────────────────────────────────────────────────────
if exist "%CD%\tsw_hud.db" (
    echo.
    echo  [OK] Ya existe %CD%\tsw_hud.db
    %PY% scripts\tools\verificar_hud_db.py
    echo.
    set /p reext="  ¿Re-extraer de todos modos en hud.exe? (S/N): "
    if /i not "!reext!"=="S" goto lanzar
)

:lanzar
echo.
echo  ============================================================
echo   SIGUIENTE: en la ventana de hud.exe
echo  ============================================================
echo   1. Pestaña  Extraction
echo   2. Settings ^> TSW install folder:
echo        %TSW_ROOT%
echo   3. Load my DLCs  ^(tarda: varios minutos segun DLCs^)
echo   4. Al terminar, en Settings o carpeta del HUD, copia:
echo        tsw_hud.db  --^>  %CD%\tsw_hud.db
echo      ^(o usa el boton de sincronizar BD si aparece^)
echo   5. Cierra hud.exe y ejecuta:  python scripts\tools\verificar_hud_db.py
echo.
echo   Para el autopilot: arranca TSW con -HTTPAPI y luego iniciar_autopilot.bat
echo  ============================================================
echo.
pause
start "" "%RUN_HUD%"
echo  hud.exe lanzado.
pause
