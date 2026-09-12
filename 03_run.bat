@echo off
setlocal
cd /d "%~dp0"
title PavlokSuperChat v1.0

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv was not found.
    echo Run 01_setup_windows.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" pavlok_superchat.py
set RC=%errorlevel%
echo.
echo Process ended. Exit code: %RC%
pause
exit /b %RC%
