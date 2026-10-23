@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title Thinking mode

echo ==========================================
echo   DeepSeek thinking mode
echo ==========================================
echo   1) off   no thinking, fastest (default)
echo   2) low   light thinking
echo   3) high  deep thinking
echo.
set "C="
set /p "C=Pick 1/2/3 then press Enter: "

if "%C%"=="1" set "MODE=off"
if "%C%"=="2" set "MODE=low"
if "%C%"=="3" set "MODE=high"
if not defined MODE (
    echo Invalid choice.
    pause
    exit /b 1
)

"local\venv\Scripts\python.exe" "%~dp0toggle_thinking.py" %MODE%
echo.
pause
