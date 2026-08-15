@echo off
setlocal
cd /d "%~dp0"

if not "%~1"=="" set "TTS_API_PORT=%~1"
if not defined TTS_API_PORT set "TTS_API_PORT=8090"

echo ===============================================
echo GOOGLE TRANSLATE STANDALONE TTS API V1
echo ===============================================

py -c "import requests" >nul 2>&1
if errorlevel 1 (
    echo Dang cai requests...
    py -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Cai requests that bai.
        if /i not "%MODULE_HUB_MANAGED%"=="1" pause
        exit /b 1
    )
)

echo.
echo TTS API: http://127.0.0.1:%TTS_API_PORT%
echo Voices : http://127.0.0.1:%TTS_API_PORT%/voices
echo Ctrl+C de dung.
echo.

py tts_api.py --host 127.0.0.1 --port %TTS_API_PORT%
set "EXIT_CODE=%ERRORLEVEL%"
if /i not "%MODULE_HUB_MANAGED%"=="1" pause
endlocal & exit /b %EXIT_CODE%
