@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Miyako - One Click Start

set "PY=%~dp0local\venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] local\venv\Scripts\python.exe not found.
    echo         Run this from the qq-bot folder.
    pause
    exit /b 1
)

echo ==================================================
echo    Miyako QQ Bot - one click start
echo ==================================================
echo.
echo   Step 1 of 3   voice service   port 9880
echo   Step 2 of 3   AstrBot         ports 6185 / 6199
echo   Step 3 of 3   QQ + NapCat     scan QR if needed
echo.
echo   Each step opens its own window. Do not close them.
echo.

rem ---------------------------------------------------------
rem 1) voice service
rem ---------------------------------------------------------
echo [1/3] Voice service ...
"%PY%" "%~dp0tools\port_check.py" 9880
if not errorlevel 1 (
    echo       Already running. Skipping.
    goto step_bot
)

echo       Starting GPT-SoVITS in a new window.
echo       First load takes 40-90s. Keep that window open.
start "GPT-SoVITS" cmd /k ""%~dp0tools\start-gsv.bat""

set /a WAIT=0
echo       Waiting for port 9880 .
:wait_gsv
"%SystemRoot%\System32\ping.exe" -n 3 127.0.0.1 >nul
"%PY%" "%~dp0tools\port_check.py" 9880
if not errorlevel 1 goto gsv_ok
<nul set /p="."
set /a WAIT+=2
if !WAIT!==30 echo.
if !WAIT!==30 echo       Still loading models ... this is normal.
if !WAIT!==90 echo.
if !WAIT!==90 echo       Taking long. Check the GPT-SoVITS window.
if !WAIT! lss 120 goto wait_gsv

echo.
echo       [WARN] 9880 did not answer in 120s.
echo              Look at the GPT-SoVITS window for the error.
echo              Continuing WITHOUT voice.
goto step_bot

:gsv_ok
echo.
echo       Voice service ready.

rem ---------------------------------------------------------
rem 2) AstrBot
rem ---------------------------------------------------------
:step_bot
echo.
echo [2/3] AstrBot ...
"%PY%" "%~dp0tools\port_check.py" 6199
if not errorlevel 1 (
    echo       AstrBot is already running on 6199 - not starting a second one.
    echo       NOTE: config edits only take effect after a restart.
    echo             Run tools\stop-astrbot.bat, then run this script again.
    goto step_qq
)

call "%~dp0tools\start-astrbot.bat"
if errorlevel 1 (
    echo.
    echo [X] AstrBot did not start. Fix the error above and run this again.
    pause
    exit /b 1
)

set /a WAIT2=0
echo       Waiting for port 6199 .
:wait_bot
"%SystemRoot%\System32\ping.exe" -n 3 127.0.0.1 >nul
"%PY%" "%~dp0tools\port_check.py" 6199
if not errorlevel 1 goto bot_ok
<nul set /p="."
set /a WAIT2+=2
if !WAIT2!==30 echo.
if !WAIT2!==30 echo       Still starting ... this is normal.
if !WAIT2! lss 60 goto wait_bot

echo.
echo       [WARN] 6199 not answering yet. Check the AstrBot window.
goto step_qq

:bot_ok
echo.
echo       AstrBot ready.   WebUI: http://127.0.0.1:6185

rem ---------------------------------------------------------
rem 3) QQ + NapCat
rem ---------------------------------------------------------
:step_qq
echo.
echo [3/3] QQ + NapCat ...
"%PY%" "%~dp0tools\port_check.py" 6099
if not errorlevel 1 (
    echo       NapCat is already running on 6099 - not starting a second one.
    echo       Opening its web UI so you can check / scan.
    start "" http://127.0.0.1:6099
    goto qr_hint
)

start "NapCat" cmd /k ""%~dp0tools\launch-napcat.bat""
echo       NapCat + QQ window is opening ...

set /a WAIT3=0
echo       Waiting for NapCat web UI (6099) .
:wait_nap
"%SystemRoot%\System32\ping.exe" -n 3 127.0.0.1 >nul
"%PY%" "%~dp0tools\port_check.py" 6099
if not errorlevel 1 goto nap_ok
<nul set /p="."
set /a WAIT3+=2
if !WAIT3!==30 echo.
if !WAIT3!==30 echo       QQ is still starting up ... this is normal.
if !WAIT3! lss 60 goto wait_nap
echo.
echo       [WARN] 6099 not answering yet. Check the NapCat window.
goto qr_hint

:nap_ok
echo.
echo       NapCat web UI ready. Opening it in your browser.
start "" http://127.0.0.1:6099

:qr_hint
echo.
echo   ==========================================
echo      SCAN THE QR CODE TO LOG IN
echo      In the QQ window, or in the NapCat page
echo      http://127.0.0.1:6099
echo      Log in with the BOT account, not yours.
echo   ==========================================
echo.
echo       After login:
echo         NapCat window  -  ws client connected
echo         AstrBot window -  adapter connected
echo.
echo       If the QQ window closed instantly, right-click
echo       tools\launch-napcat.bat, Run as administrator.

:done
echo.
echo ==================================================
echo    All steps done.
echo.
echo    Keep these windows open:
echo      [GPT-SoVITS]  voice
echo      [AstrBot]     text and logic
echo      [NapCat]      QQ
echo.
echo    WebUI      http://127.0.0.1:6185
echo    Problems?  run tools\doctor.bat
echo ==================================================
echo.
pause
