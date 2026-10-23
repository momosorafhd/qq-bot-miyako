@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title QQ Bot Launcher

rem Docker may be installed on a custom drive
set "DOCKER_BIN=E:\Docker\Program\resources\bin"
if exist "%DOCKER_BIN%\docker.exe" set "PATH=%DOCKER_BIN%;%PATH%"

if /i "%~1"=="stop" goto stop
if /i "%~1"=="status" goto status
if /i "%~1"=="logs" goto logs

echo ==========================================
echo   QQ Bot  -  NapCat + AstrBot + DeepSeek
echo ==========================================
echo.

where docker >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker not found in PATH.
    echo         Install Docker Desktop first:
    echo         https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)

docker info >nul 2>nul
if not errorlevel 1 goto dockerok

echo [..] Docker engine is not running. Starting Docker Desktop...
set "DD_EXE="
if exist "E:\Docker\Program\Docker Desktop.exe" set "DD_EXE=E:\Docker\Program\Docker Desktop.exe"
if not defined DD_EXE if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" set "DD_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
if not defined DD_EXE (
    echo [ERROR] Docker Desktop not found.
    echo         Expected at E:\Docker\Program or Program Files.
    echo         Start Docker Desktop manually, then run this script again.
    echo.
    pause
    exit /b 1
)
start "" "%DD_EXE%"
call :waitdocker
if errorlevel 1 exit /b 1

:dockerok
if not exist ".env" (
    echo [WARN] .env not found. Creating it from .env.example...
    copy ".env.example" ".env" >nul
)

set "DEEPSEEK_KEY="
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"DEEPSEEK_API_KEY=" ".env"`) do set "DEEPSEEK_KEY=%%B"
if "!DEEPSEEK_KEY!"=="" (
    echo.
    echo [WARN] DEEPSEEK_API_KEY is empty in .env
    echo        Opening .env in Notepad. Paste your key after the "=" sign,
    echo        save the file, then run this script again.
    echo.
    start "" notepad "%~dp0.env"
    pause
    exit /b 1
)

echo [1/2] Starting containers...
docker compose up -d
if errorlevel 1 (
    echo.
    echo [ERROR] docker compose failed. Check the output above.
    echo         If it is a port conflict, edit the ports in .env.
    pause
    exit /b 1
)

echo [2/2] Waiting for services...
"%SystemRoot%\System32\ping.exe" -n 9 127.0.0.1 >nul

echo.
echo ==========================================
echo   URLs
echo ==========================================
echo   NapCat WebUI : http://127.0.0.1:6099/webui
echo   AstrBot      : http://127.0.0.1:6185
echo.
echo   AstrBot login: astrbot / ASTRBOT_DASHBOARD_PASSWORD in .env
echo   NapCat token : NAPCAT_WEBUI_TOKEN in .env
echo.
docker compose ps
echo.
start "" http://127.0.0.1:6099/webui
start "" http://127.0.0.1:6185
echo Done. Press any key to close this window.
pause >nul
exit /b 0

:stop
echo Stopping containers...
docker compose down
echo Done.
pause
exit /b 0

:status
docker compose ps
pause
exit /b 0

:logs
docker compose logs -f --tail 100
exit /b 0

:waitdocker
set /a tries=0
:wdloop
"%SystemRoot%\System32\ping.exe" -n 4 127.0.0.1 >nul
docker info >nul 2>nul
if not errorlevel 1 exit /b 0
set /a tries+=1
if !tries! geq 40 (
    echo [ERROR] Docker did not start within 2 minutes.
    echo         Open Docker Desktop and check for errors.
    echo.
    pause
    exit /b 1
)
goto wdloop
