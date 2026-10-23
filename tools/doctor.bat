@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title Doctor

if not exist "local\venv\Scripts\python.exe" (
    echo [ERROR] local\venv not found.
    pause
    exit /b 1
)

"local\venv\Scripts\python.exe" "%~dp0doctor.py"
echo.
pause
