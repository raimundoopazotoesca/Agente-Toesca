@echo off
REM Refresh mensual de UF + precios bursatiles + KPIs.
REM Se agenda con Windows Task Scheduler (ver README o instrucciones abajo).

cd /d "%~dp0.."
set LOGFILE=logs\refresh_market_data.log
if not exist logs mkdir logs

echo. >> "%LOGFILE%"
echo === %date% %time% === >> "%LOGFILE%"
python scripts\refresh_market_data.py >> "%LOGFILE%" 2>&1
echo Exit code: %errorlevel% >> "%LOGFILE%"
