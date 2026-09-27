@echo off
title Deploy now-playing page to Volumio
cd /d "%~dp0"

rem Copies only nowplaying.py. Your settings (config.json on Volumio) are left alone.

set HOST=192.168.1.174
set USER=volumio
set PASS=volumio

if not exist nowplaying.py (
    echo nowplaying.py was not found in this folder.
    echo Put deploy.bat in the same folder as nowplaying.py and try again.
    echo.
    pause
    exit /b
)

rem Warn if the browser saved a newer download under a different name
for %%F in ("nowplaying (*).py") do (
    echo Note: found "%%~nxF" in this folder. If that's the newest download,
    echo rename it to nowplaying.py first, or this will send the older file.
    echo.
)

echo Copying nowplaying.py to Volumio...
pscp -pw %PASS% nowplaying.py %USER%@%HOST%:/home/volumio/nowplaying/
if errorlevel 1 goto fail

echo.
echo Restarting the page...
plink -pw %PASS% %USER%@%HOST% "echo %PASS% | sudo -S systemctl restart nowplaying"
if errorlevel 1 goto fail

echo.
echo Checking it started...
timeout /t 3 /nobreak >nul
plink -pw %PASS% %USER%@%HOST% "systemctl is-active nowplaying"
if errorlevel 1 (
    echo.
    echo The page didn't start. To see why, run:
    echo   ssh volumio@%HOST% "journalctl -u nowplaying -n 30 --no-pager"
    echo.
    pause
    exit /b
)

echo.
echo Done. Reload the page on the TV.
echo.
pause
exit /b

:fail
echo.
echo Something went wrong - see the message above.
echo If it asked about a host key, answer y and run this again.
echo.
pause
