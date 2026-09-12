@echo off
setlocal
cd /d "%~dp0"
title PavlokSuperChat - EXE Build

echo ====================================================
echo  PavlokSuperChat - Windows EXE Build
echo ====================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv was not found.
    echo Run 01_setup_windows.bat first.
    pause
    exit /b 1
)

if not exist "config.ini" (
    echo [ERROR] config.ini was not found.
    pause
    exit /b 1
)

if not exist "README.txt" (
    echo [ERROR] README.txt was not found.
    pause
    exit /b 1
)

echo [1/4] Installing or updating PyInstaller...
".venv\Scripts\python.exe" -m pip install --upgrade -r requirements-dev.txt
if errorlevel 1 goto BUILD_ERROR

echo.
echo [2/4] Removing previous build output...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo.
echo [3/4] Building PavlokSuperChat.exe...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean PavlokSuperChat.spec
if errorlevel 1 goto BUILD_ERROR

if not exist "dist\PavlokSuperChat.exe" (
    echo [ERROR] dist\PavlokSuperChat.exe was not created.
    goto BUILD_ERROR
)

echo.
echo [4/4] Copying user files...
copy /Y "config.ini" "dist\config.ini" >nul
if errorlevel 1 goto BUILD_ERROR
copy /Y "README.txt" "dist\README.txt" >nul
if errorlevel 1 goto BUILD_ERROR

echo.
echo ====================================================
echo  BUILD OK
echo ====================================================
echo Output:
echo   %CD%\dist\PavlokSuperChat.exe
echo   %CD%\dist\config.ini
echo   %CD%\dist\README.txt
echo.
echo The target PC does not need Python installed.
echo.
pause
exit /b 0

:BUILD_ERROR
echo.
echo ====================================================
echo  BUILD FAILED
echo ====================================================
echo Review the error messages above.
echo.
pause
exit /b 1
