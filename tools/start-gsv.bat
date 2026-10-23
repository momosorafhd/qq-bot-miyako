@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."
title GPT-SoVITS API

set "GSV_HOME=F:\GPT-SoVITS-v2pro-20250604"

if not exist "%GSV_HOME%\api_v2.py" (
    echo [ERROR] GPT-SoVITS not found at:
    echo         %GSV_HOME%
    echo         Edit GSV_HOME in this .bat if you moved the folder.
    pause
    exit /b 1
)

echo ==========================================
echo   GPT-SoVITS API  (port 9880)
echo ==========================================
echo   Close this window to stop the voice service.
echo.

cd /d "%GSV_HOME%"
".\runtime\python.exe" api_v2.py -a 127.0.0.1 -p 9880

echo.
echo Service exited.
pause
