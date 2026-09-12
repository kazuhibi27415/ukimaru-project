@echo off
setlocal
cd /d "%~dp0"
title PavlokSuperChat - Setup

echo ================================================
echo  PavlokSuperChat Windows Setup
echo ================================================
echo.

if exist ".venv\Scripts\python.exe" goto INSTALL

where py >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Python Launcher ^(py^) found.
    py -3 --version
    echo Creating virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 goto VENV_ERROR
    goto INSTALL
)

where python >nul 2>&1
if %errorlevel%==0 (
    echo [OK] python found.
    python --version
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto VENV_ERROR
    goto INSTALL
)

echo [ERROR] Python was not found.
echo Install 64-bit Python 3.13.x, then run this file again.
echo https://www.python.org/downloads/windows/
echo.
pause
exit /b 1

:INSTALL
echo.
echo Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto PIP_ERROR

echo.
echo Installing runtime packages...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto PIP_ERROR

echo.
echo ================================================
echo  Setup completed successfully.
echo ================================================
echo Next:
echo   1. Edit config.ini
echo   2. Run 02_test_pavlok_auth.bat
echo   3. Run 03_run.bat
echo.
pause
exit /b 0

:VENV_ERROR
echo [ERROR] Failed to create .venv.
pause
exit /b 1

:PIP_ERROR
echo [ERROR] Package installation failed.
pause
exit /b 1
