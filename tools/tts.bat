@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."
title TTS setup

if not exist "local\venv\Scripts\python.exe" (
    echo [ERROR] local\venv not found.
    pause
    exit /b 1
)

echo ==========================================
echo   1) status      show files and config
echo   2) on          auto-detect from voice\ folder
echo   3) off         disable voice
echo   4) on (manual) type paths by hand
echo   5) mode        how often she speaks
echo ==========================================
echo.
echo   Put files here:
echo     voice\weights\   *.pth (SoVITS) + *.ckpt (GPT)
echo     voice\ref\       *.wav (3-10s) + optional prompt.txt
echo.
set "C="
set /p "C=Pick 1-5 then press Enter: "

if "%C%"=="1" (
    "local\venv\Scripts\python.exe" "%~dp0tts_setup.py" status
    goto end
)
if "%C%"=="2" (
    echo.
    echo Scanning voice\ ...
    "local\venv\Scripts\python.exe" "%~dp0tts_setup.py" on
    goto end
)
if "%C%"=="3" (
    "local\venv\Scripts\python.exe" "%~dp0tts_setup.py" off
    goto end
)
if "%C%"=="5" (
    echo.
    echo   1. voice   every reply is a voice message
    echo   2. both    voice + text
    echo   3. rare    occasionally, mostly text
    echo.
    set "MD="
    set /p "MD=Pick 1/2/3: "
    if "!MD!"=="1" "local\venv\Scripts\python.exe" "%~dp0tts_setup.py" mode voice
    if "!MD!"=="2" "local\venv\Scripts\python.exe" "%~dp0tts_setup.py" mode both
    if "!MD!"=="3" "local\venv\Scripts\python.exe" "%~dp0tts_setup.py" mode rare
    goto end
)
if "%C%"=="4" (
    echo.
    set "SOVITS="
    set "GPTW="
    set "REF="
    set "PTXT="
    set /p "SOVITS=SoVITS weight (.pth) full path: "
    set /p "GPTW=GPT weight (.ckpt) full path: "
    set /p "REF=Reference audio (.wav) full path: "
    set /p "PTXT=Text spoken in the reference audio: "
    "local\venv\Scripts\python.exe" "%~dp0tts_setup.py" on --sovits "!SOVITS!" --gpt "!GPTW!" --ref "!REF!" --prompt-text "!PTXT!"
    goto end
)
echo Nothing changed.

:end
echo.
pause
