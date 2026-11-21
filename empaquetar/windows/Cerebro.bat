@echo off
rem Cerebro local: arranca el servidor. Abre http://localhost:8765 en el navegador.
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
start "" /b cmd /c "timeout /t 6 >nul & start http://localhost:8765"
"%~dp0python\python.exe" -s -m cerebro %*
if errorlevel 1 pause
