@echo off
setlocal
cd /d "%~dp0"
title PavlokSuperChat - EXE Test

if not exist "dist\PavlokSuperChat.exe" (
    echo [ERROR] dist\PavlokSuperChat.exe was not found.
    echo Run 04_build_exe.bat first.
    pause
    exit /b 1
)

if not exist "dist\config.ini" (
    echo [ERROR] dist\config.ini was not found.
    pause
    exit /b 1
)

cd /d "%~dp0dist"
PavlokSuperChat.exe
set RC=%errorlevel%
echo.
echo Process ended. Exit code: %RC%
pause
exit /b %RC%
