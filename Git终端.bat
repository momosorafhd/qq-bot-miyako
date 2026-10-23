@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Git Bash - qq-bot

set "GB=D:\Git\git-bash.exe"
if exist "%GB%" (
    start "" "%GB%" --cd="%~dp0."
    exit /b 0
)

rem fallback locations
for %%P in (
    "C:\Program Files\Git\git-bash.exe"
    "C:\Program Files (x86)\Git\git-bash.exe"
) do if exist %%P (
    start "" %%P --cd="%~dp0."
    exit /b 0
)

echo [ERROR] git-bash.exe not found.
echo         Tried: D:\Git\git-bash.exe and Program Files.
echo.
echo Use this instead: type  cmd  in the Explorer address bar,
echo then run git commands there (git is already in PATH).
pause
