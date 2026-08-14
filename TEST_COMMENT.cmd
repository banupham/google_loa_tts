@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
py test_comment.py
echo.
pause
