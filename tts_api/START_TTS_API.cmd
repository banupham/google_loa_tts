@echo off
setlocal
cd /d "%~dp0"

echo ===============================================
echo GOOGLE TRANSLATE STANDALONE TTS API V1
echo ===============================================

py -c "import requests" >nul 2>&1
if errorlevel 1 (
    echo Dang cai requests...
    py -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Cai requests that bai.
        pause
        exit /b 1
    )
)

echo.
echo TTS API: http://127.0.0.1:8090
echo Voices : http://127.0.0.1:8090/voices
echo Ctrl+C de dung.
echo.

py tts_api.py --host 127.0.0.1 --port 8090
pause
