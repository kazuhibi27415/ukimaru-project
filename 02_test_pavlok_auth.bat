@echo off
setlocal
cd /d "%~dp0"
title PavlokSuperChat - Pavlok Auth Test

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv was not found.
    echo Run 01_setup_windows.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" test_pavlok_auth.py
set RC=%errorlevel%
echo.
echo Process ended. Exit code: %RC%
pause
exit /b %RC%
