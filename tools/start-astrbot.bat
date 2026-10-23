@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."
title AstrBot launcher

rem Clear proxy env vars so the LLM API is reached directly.
set "http_proxy="
set "https_proxy="
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "all_proxy="
set "ALL_PROXY="

rem Read the key. Everything after the first "=" is taken verbatim.
set "DEEPSEEK_KEY="
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"DEEPSEEK_API_KEY=" ".env"`) do set "DEEPSEEK_KEY=%%B"

rem Strip trailing spaces. A trailing space makes the Authorization header
rem invalid and shows up in AstrBot as "APIConnectionError: Connection error."
for /l %%i in (1,1,8) do if "!DEEPSEEK_KEY:~-1!"==" " set "DEEPSEEK_KEY=!DEEPSEEK_KEY:~0,-1!"

if "!DEEPSEEK_KEY!"=="" (
    echo [ERROR] DEEPSEEK_API_KEY is empty in .env
    start "" notepad "%~dp0..\.env"
    pause
    exit /b 1
)

rem Vision key (Zhipu). Optional: empty means image recognition stays off.
set "ZHIPU_KEY="
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"ZHIPU_API_KEY=" ".env"`) do set "ZHIPU_KEY=%%B"
for /l %%i in (1,1,8) do if "!ZHIPU_KEY:~-1!"==" " set "ZHIPU_KEY=!ZHIPU_KEY:~0,-1!"

rem Export here and let the child cmd inherit it.
set "DEEPSEEK_API_KEY=!DEEPSEEK_KEY!"
set "ZHIPU_API_KEY=!ZHIPU_KEY!"

rem Preflight: the key must carry no whitespace at all.
"local\venv\Scripts\python.exe" -c "import os,sys;k=os.environ.get('DEEPSEEK_API_KEY','');sys.exit(0 if k and k==k.strip() else 1)"
if errorlevel 1 (
    echo [ERROR] DEEPSEEK_API_KEY still contains whitespace.
    echo         Open .env, delete that line and paste the key again.
    start "" notepad "%~dp0..\.env"
    pause
    exit /b 1
)

echo Key OK.

rem Voice preflight: AstrBot pushes weights to 9880 only at startup.
rem If the voice service is down now, this launch will have NO voice.
"local\venv\Scripts\python.exe" "%~dp0voice_status.py"
if errorlevel 1 (
    echo.
    echo   [WARN] Voice service not running on 9880.
    echo          This launch is TEXT ONLY, no voice.
    echo          For voice: run start-gsv.bat, wait ~40s, then run this again.
    echo.
)

echo Starting AstrBot in a new window ...
start "AstrBot" /D "%~dp0..\local\AstrBot" cmd /k "..\venv\Scripts\astrbot.exe run"
