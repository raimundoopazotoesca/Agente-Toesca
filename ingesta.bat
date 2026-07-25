@echo off
cd /d "%~dp0"
echo Iniciando servidor de ingesta en http://127.0.0.1:8765/ingesta ...
echo.
REM El navegador se abre con 3s de retraso: antes se abria antes de que Flask
REM escuchara y la primera carga fallaba (habia que recargar con F5).
start "" /b cmd /c "timeout /t 3 >nul && start "" http://127.0.0.1:8765/ingesta"
python -X utf8 -m scripts.ingesta_server
