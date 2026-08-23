@echo off
chcp 65001 >nul
title Instalar Rust para compilar hud.exe
echo.
echo  Instalando Rustup ^(toolchain stable^) via winget...
echo  Acepta el instalador si Windows lo pide.
echo.
winget install Rustlang.Rustup --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo  [ERROR] winget fallo. Instala manualmente desde https://rustup.rs
    pause & exit /b 1
)

echo.
echo  Cierra y abre una terminal nueva, o ejecuta:
echo    refrescar_path_rust.bat
echo.
pause
