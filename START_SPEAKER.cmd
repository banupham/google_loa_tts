@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo ============================================================
echo GOOGLE TTS API -> TIKTOK SPEAKER
echo ============================================================
echo.

py -c "import fastapi,uvicorn,requests,pydantic" >nul 2>&1
if errorlevel 1 (
    echo Dang cai dependency...
    py -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Cai dependency that bai.
        pause
        exit /b 1
    )
)

echo.
echo TTS API can chay truoc:
echo   http://127.0.0.1:8090/health
echo.
echo Speaker:
echo   http://127.0.0.1:9000
echo Webhook:
echo   http://127.0.0.1:9000/tiktok-event
echo.

py app.py
pause
