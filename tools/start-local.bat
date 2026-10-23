@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."
title QQ Bot - local mode

rem Clear proxy env vars so the LLM API is reached directly.
set "http_proxy="
set "https_proxy="
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "all_proxy="
set "ALL_PROXY="

rem ---------- read .env ----------
set "DEEPSEEK_KEY="
set "NAPCAT_TOKEN="
set "DASH_PWD="
set "ZHIPU_KEY="
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"DEEPSEEK_API_KEY=" ".env"`) do set "DEEPSEEK_KEY=%%B"
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"NAPCAT_WEBUI_TOKEN=" ".env"`) do set "NAPCAT_TOKEN=%%B"
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"ASTRBOT_DASHBOARD_PASSWORD=" ".env"`) do set "DASH_PWD=%%B"
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"ZHIPU_API_KEY=" ".env"`) do set "ZHIPU_KEY=%%B"

rem Strip trailing spaces from the key. A trailing space makes the Authorization
rem header invalid and shows up in AstrBot as "APIConnectionError: Connection error."
for /l %%i in (1,1,8) do if "!DEEPSEEK_KEY:~-1!"==" " set "DEEPSEEK_KEY=!DEEPSEEK_KEY:~0,-1!"
for /l %%i in (1,1,8) do if "!ZHIPU_KEY:~-1!"==" " set "ZHIPU_KEY=!ZHIPU_KEY:~0,-1!"

if "!DEEPSEEK_KEY!"=="" (
    echo [ERROR] DEEPSEEK_API_KEY is empty in .env
    echo         Opening .env in Notepad. Paste your key after the "=" sign,
    echo         save the file, then run this script again.
    start "" notepad "%~dp0..\.env"
    pause
    exit /b 1
)

if not exist "local\venv\Scripts\astrbot.exe" (
    echo [ERROR] AstrBot is not installed in local\venv
    pause
    exit /b 1
)

rem ---------- locate QQ.exe ----------
set "QQPath="
if exist "E:\QQ.exe" set "QQPath=E:\QQ.exe"
if not defined QQPath if exist "E:\QQ\QQ.exe" set "QQPath=E:\QQ\QQ.exe"
if not defined QQPath if exist "%ProgramFiles%\Tencent\QQNT\QQ.exe" set "QQPath=%ProgramFiles%\Tencent\QQNT\QQ.exe"
if not defined QQPath if exist "%ProgramFiles(x86)%\Tencent\QQNT\QQ.exe" set "QQPath=%ProgramFiles(x86)%\Tencent\QQNT\QQ.exe"
if not defined QQPath if exist "%LOCALAPPDATA%\Programs\Tencent\QQNT\QQ.exe" set "QQPath=%LOCALAPPDATA%\Programs\Tencent\QQNT\QQ.exe"

if not defined QQPath (
    echo [WARN] QQ.exe not found. NapCat will not start.
    echo        Install QQ first, then run this script again.
    echo.
    pause
)

echo ==========================================
echo   QQ      : !QQPath!
echo   AstrBot : http://127.0.0.1:6185
echo   NapCat  : http://127.0.0.1:6099
echo ==========================================
echo.

echo Starting AstrBot...
rem Export at this level and let the child cmd inherit it.
rem Never write:  set VAR=value && prog  -- that appends a trailing space to value.
set "DEEPSEEK_API_KEY=!DEEPSEEK_KEY!"
set "ZHIPU_API_KEY=!ZHIPU_KEY!"
"%~dp0..\local\venv\Scripts\python.exe" -c "import os,sys;k=os.environ.get('DEEPSEEK_API_KEY','');sys.exit(0 if k and k==k.strip() else 1)"
if errorlevel 1 (
    echo [ERROR] DEEPSEEK_API_KEY still contains whitespace.
    echo         Open .env, delete that line and paste the key again.
    start "" notepad "%~dp0..\.env"
    pause
    exit /b 1
)
start "AstrBot" /D "%~dp0..\local\AstrBot" cmd /k "..\venv\Scripts\astrbot.exe run"

if defined QQPath (
    echo Starting NapCat + QQ...
    start "NapCat" cmd /k "%~dp0launch-napcat.bat"
)

echo.
echo Waiting for services...
"%SystemRoot%\System32\ping.exe" -n 16 127.0.0.1 >nul

start "" http://127.0.0.1:6185
start "" http://127.0.0.1:6099

echo.
echo ==========================================
echo   AstrBot WebUI : http://127.0.0.1:6185
echo     user  astrbot
echo     pass  !DASH_PWD!
echo.
echo   NapCat WebUI  : http://127.0.0.1:6099
echo     token !NAPCAT_TOKEN!
echo.
echo   OneBot link   : ws://127.0.0.1:6199/ws  (already configured)
echo ==========================================
echo.
echo Keep all windows open. Closing them stops the bot.
pause
