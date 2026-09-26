@echo off
title Deploy now-playing page to Volumio
cd /d "%~dp0"

set HOST=192.168.1.174
set USER=volumio
set PASS=volumio

echo Copying nowplaying.py and config.json to Volumio...
pscp -pw %PASS% nowplaying.py config.json %USER%@%HOST%:/home/volumio/nowplaying/
if errorlevel 1 goto fail

echo.
echo Restarting the page...
plink -pw %PASS% %USER%@%HOST% "echo %PASS% | sudo -S systemctl restart nowplaying"
if errorlevel 1 goto fail

echo.
echo Done. Refresh the page on the TV.
echo.
pause
exit /b

:fail
echo.
echo Something went wrong - see the message above.
echo If it asked about a host key, answer y and run this again.
echo.
pause
