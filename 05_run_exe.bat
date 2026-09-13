@echo off
setlocal
cd /d "%~dp0"
title PavlokSuperChat - EXE Test

set /p APP_VERSION=<VERSION.txt
set "RELEASE_DIR=releases\v%APP_VERSION%"
if not exist "%RELEASE_DIR%\PavlokSuperChat.exe" (
    echo [ERROR] Release EXE was not found.
    echo Run 04_build_exe.bat first.
    pause
    exit /b 1
)

cd /d "%~dp0%RELEASE_DIR%"
PavlokSuperChat.exe
set RC=%errorlevel%
echo.
echo Process ended. Exit code: %RC%
pause
exit /b %RC%
