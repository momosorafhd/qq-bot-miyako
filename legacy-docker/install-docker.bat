@echo off
setlocal
cd /d "%~dp0"
title Install Docker Desktop to E:

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator privileges required.
    echo         Right-click this file, then choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

set "INSTALLER=C:\Users\sora\Downloads\docker-installer\Docker Desktop_4.95.0_Machine_X64_exe_en-US.exe"
if not exist "%INSTALLER%" (
    echo [ERROR] Installer not found:
    echo         %INSTALLER%
    echo         Download it again, or edit INSTALLER in this file.
    echo.
    pause
    exit /b 1
)

if not exist "E:\Docker\Program" mkdir "E:\Docker\Program"
if not exist "E:\Docker\WSL" mkdir "E:\Docker\WSL"
if not exist "E:\Docker\Containers" mkdir "E:\Docker\Containers"
if not exist "E:\Docker\temp" mkdir "E:\Docker\temp"

rem Keep the installer's temporary files off the C drive too
set "TEMP=E:\Docker\temp"
set "TMP=E:\Docker\temp"

echo.
echo Installing Docker Desktop
echo   program  : E:\Docker\Program
echo   wsl data : E:\Docker\WSL
echo   win ctr  : E:\Docker\Containers
echo.
echo This takes 5-10 minutes. Keep this window open.
echo.

"%INSTALLER%" install --accept-license --installation-dir="E:\Docker\Program" --wsl-default-data-root="E:\Docker\WSL" --windows-containers-default-data-root="E:\Docker\Containers"

set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" (
    echo [ERROR] Installer exited with code %RC%.
    echo         Check logs under %%TEMP%%\Docker Desktop Installer
    echo.
    pause
    exit /b %RC%
)

echo [OK] Install finished.
echo      1. Reboot if Windows asks.
echo      2. Launch Docker Desktop from E:\Docker\Program
echo      3. Accept terms, skip sign-in, wait for "Engine running".
echo      4. Run start.bat again.
echo.
pause
exit /b 0
