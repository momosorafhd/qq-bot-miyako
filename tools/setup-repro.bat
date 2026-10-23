@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title Setup - reproduce config and persona

set "PY=%~dp0..\local\venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] local\venv\Scripts\python.exe not found.
    echo         Follow REPRODUCE.md step 2 to create the venv first.
    pause
    exit /b 1
)

"%PY%" "%~dp0setup_repro.py"
echo.
pause
