@echo off
rem Hace que Cerebro arranque al encender el PC, aunque nadie inicie sesión en Windows.
rem Usa el Programador de tareas (cuenta SYSTEM): CUDA funciona igual sin escritorio.
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  echo Hace falta ejecutarlo como administrador: clic derecho ^> "Ejecutar como administrador".
  pause & exit /b 1
)
if not exist "%~dp0datos\estado" mkdir "%~dp0datos\estado"
schtasks /Create /F /TN "Cerebro local" /SC ONSTART /DELAY 0000:30 /RU SYSTEM /RL HIGHEST /TR "\"%~dp0servicio.cmd\""
rem Que el móvil pueda entrar por la Wi-Fi de casa (solo redes privadas)
netsh advfirewall firewall delete rule name="Cerebro local" >nul 2>&1
netsh advfirewall firewall add rule name="Cerebro local" dir=in action=allow protocol=TCP localport=8765 profile=private
schtasks /Run /TN "Cerebro local"
echo.
echo Listo. Cerebro arrancará solo cada vez que enciendas el PC.
echo Interfaz: http://localhost:8765   (desde el móvil: http://IP-de-este-PC:8765)
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo   IP de este PC:%%a
pause
