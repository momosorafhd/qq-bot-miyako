@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title Apply persona

if not exist "local\venv\Scripts\python.exe" (
    echo [ERROR] local\venv not found.
    pause
    exit /b 1
)

"local\venv\Scripts\python.exe" "%~dp0apply_persona.py"
echo.
pause
