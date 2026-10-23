@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."
title Voice dataset screener

if not exist "local\venv\Scripts\python.exe" (
    echo [ERROR] local\venv not found.
    pause
    exit /b 1
)

set "D=%~1"
if "%D%"=="" (
    echo Drag a folder onto this .bat, or type the path below.
    echo.
    set /p "D=Dataset folder: "
)

if "%D%"=="" (
    echo Nothing to scan.
    pause
    exit /b 1
)

echo.
echo === Scan only (no files moved) ===
"local\venv\Scripts\python.exe" "%~dp0voice_screener.py" "%D%"
echo.
echo.
set "M="
set /p "M=Move files into _keep/_check/_reject? (y/N): "
if /i "%M%"=="y" (
    echo.
    echo === Moving ===
    "local\venv\Scripts\python.exe" "%~dp0voice_screener.py" "%D%" --move --quiet
)
echo.
pause
