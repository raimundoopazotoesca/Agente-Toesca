@echo off
cd /d "%~dp0"
echo Abriendo pantalla de ingesta EEFF en http://localhost:8765/ingesta ...
start "" http://localhost:8765/ingesta
python -m scripts.ingesta_server
