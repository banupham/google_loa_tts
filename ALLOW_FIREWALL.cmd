@echo off
net session >nul 2>&1
if errorlevel 1 (
  echo Hay chay file nay bang Run as administrator.
  pause
  exit /b 1
)

netsh advfirewall firewall add rule name="Google API TikTok Speaker 9000" dir=in action=allow protocol=TCP localport=9000

echo.
echo Da mo TCP 9000 tren Windows Firewall.
pause
