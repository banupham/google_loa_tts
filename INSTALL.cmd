@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"

py -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo CAI DAT THAT BAI
    pause
    exit /b 1
)

echo.
echo CAI DAT XONG
pause
