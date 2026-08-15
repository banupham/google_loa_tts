@echo off
setlocal
cd /d "%~dp0"

echo [1] HEALTH
curl -s "http://127.0.0.1:8090/health"
echo.
echo.

echo [2] VOICES
curl -s "http://127.0.0.1:8090/voices"
echo.
echo.

echo [3] GENERATE MP3
curl -s -X POST "http://127.0.0.1:8090/tts" ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Xin chào thế giới\",\"lang\":\"vi\"}" ^
  --output test_voice.mp3

if exist test_voice.mp3 (
  echo Created: test_voice.mp3
) else (
  echo MP3 was not created.
)

echo.
pause
