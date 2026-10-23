@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title DeepSeek check

rem Clear proxy env vars, same as the launcher does.
set "http_proxy="
set "https_proxy="
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "all_proxy="
set "ALL_PROXY="

if not exist "local\venv\Scripts\python.exe" (
    echo [ERROR] local\venv not found.
    pause
    exit /b 1
)

"local\venv\Scripts\python.exe" "%~dp0check_llm.py"
echo.
pause
