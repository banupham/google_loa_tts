@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"

if not "%~1"=="" set "LOA_API_PORT=%~1"
if not defined LOA_API_PORT set "LOA_API_PORT=9000"
if not "%~2"=="" set "TTS_API_PORT=%~2"
if not defined TTS_API_PORT set "TTS_API_PORT=8090"
if not defined LOA_TTS_API_URL set "LOA_TTS_API_URL=http://127.0.0.1:%TTS_API_PORT%/tts"
if not defined LOA_TTS_HEALTH_URL set "LOA_TTS_HEALTH_URL=http://127.0.0.1:%TTS_API_PORT%/health"

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
echo TTS API:
echo   %LOA_TTS_HEALTH_URL%
echo.
echo Speaker:
echo   http://127.0.0.1:%LOA_API_PORT%
echo Webhook:
echo   http://127.0.0.1:%LOA_API_PORT%/tiktok-event
echo.

py app.py
pause
