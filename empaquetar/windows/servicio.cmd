@echo off
rem Lo lanza el Programador de tareas al encender el PC (sin iniciar sesión).
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
"%~dp0python\python.exe" -s -m cerebro >> "%~dp0datos\estado\servicio.log" 2>&1
