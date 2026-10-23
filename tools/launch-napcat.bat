@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0..\local\NapCatShell" || (echo [ERROR] local\NapCatShell not found & pause & exit /b 1)
title NapCat
chcp 65001 >nul

set "NAPCAT_PATCH_PACKAGE=%cd%\qqnt.json"
set "NAPCAT_LOAD_PATH=%cd%\loadNapCat.js"
set "NAPCAT_INJECT_PATH=%cd%\NapCatWinBootHook.dll"
set "NAPCAT_LAUNCHER_PATH=%cd%\NapCatWinBootMain.exe"
set "NAPCAT_MAIN_PATH=%cd%\napcat.mjs"

rem ---------- locate QQ.exe ----------
set "RetString="
for /f "tokens=2*" %%a in ('reg query "HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ" /v "UninstallString" 2^>nul') do set "RetString=%%~b"

set "QQPath="
if defined RetString for %%a in ("%RetString%") do set "QQPath=%%~dpaQQ.exe"
if defined QQPath if not exist "%QQPath%" set "QQPath="

if not defined QQPath if exist "E:\QQ.exe" set "QQPath=E:\QQ.exe"
if not defined QQPath if exist "E:\QQ\QQ.exe" set "QQPath=E:\QQ\QQ.exe"
if not defined QQPath if exist "%ProgramFiles%\Tencent\QQNT\QQ.exe" set "QQPath=%ProgramFiles%\Tencent\QQNT\QQ.exe"
if not defined QQPath if exist "%ProgramFiles(x86)%\Tencent\QQNT\QQ.exe" set "QQPath=%ProgramFiles(x86)%\Tencent\QQNT\QQ.exe"
if not defined QQPath if exist "%LOCALAPPDATA%\Programs\Tencent\QQNT\QQ.exe" set "QQPath=%LOCALAPPDATA%\Programs\Tencent\QQNT\QQ.exe"

if not defined QQPath (
    echo [ERROR] QQ.exe not found.
    echo         Tried: registry, E:\QQ.exe, E:\QQ\QQ.exe, Program Files.
    echo         Install QQ first, then run this again.
    pause
    exit /b 1
)

echo QQ      = %QQPath%
echo NapCat  = %cd%
echo.
echo Starting QQ with NapCat hook...
echo.

"%NAPCAT_LAUNCHER_PATH%" "%QQPath%" "%NAPCAT_INJECT_PATH%"
set "napcat_code=%ERRORLEVEL%"

echo.
echo NapCat exited. code = %napcat_code%
echo If it closed instantly, right-click this file and choose "Run as administrator".
pause
exit /b %napcat_code%
