@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 ( echo Ejecútalo como administrador. & pause & exit /b 1 )
schtasks /End /TN "Cerebro local" >nul 2>&1
schtasks /Delete /F /TN "Cerebro local"
netsh advfirewall firewall delete rule name="Cerebro local"
taskkill /F /IM llama-server.exe >nul 2>&1
powershell -NoProfile -Command "Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '%~dp0*' } | Stop-Process -Force"
echo Servicio quitado. Tus datos siguen en la carpeta "datos".
pause
