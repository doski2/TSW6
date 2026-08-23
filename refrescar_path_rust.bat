@echo off
:: Añade cargo al PATH de esta sesion (tras instalar rustup)
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
cargo --version
if errorlevel 1 (
    echo cargo no encontrado. Reinicia el PC o abre terminal nueva tras rustup.
    exit /b 1
)
echo PATH actualizado para esta ventana.
