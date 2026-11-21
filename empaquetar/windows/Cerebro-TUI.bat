@echo off
rem Interfaz de terminal. Necesita el servidor en marcha (Cerebro.bat o el servicio).
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
set PYTHONUTF8=1
"%~dp0python\python.exe" -s -m cerebro tui %*
