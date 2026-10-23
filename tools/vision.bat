@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title Image recognition

echo ==========================================
echo   Image recognition (Zhipu GLM-4V-Flash)
echo ==========================================
"local\venv\Scripts\python.exe" "%~dp0vision_setup.py" status
echo.
echo   1) on    enable image recognition
echo   2) off   disable it
echo   3) open .env  (paste ZHIPU_API_KEY here)
echo.
set "C="
set /p "C=Pick 1/2/3 then press Enter: "

if "%C%"=="1" (
    "local\venv\Scripts\python.exe" "%~dp0vision_setup.py" on
    goto end
)
if "%C%"=="2" (
    "local\venv\Scripts\python.exe" "%~dp0vision_setup.py" off
    goto end
)
if "%C%"=="3" (
    start "" notepad "%~dp0..\.env"
    goto end
)
echo Nothing changed.

:end
echo.
pause
