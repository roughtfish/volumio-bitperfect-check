@echo off
setlocal
title Back up now-playing settings to Google Drive
cd /d "%~dp0"

rem Downloads the now-playing settings backup (with keys) from Volumio and
rem saves a dated copy into a folder in your Google Drive. Changes nothing
rem on the box. Keep the Drive folder private: the file contains your keys.

set HOST=192.168.1.174
set PORT=8080
set DEST=G:\My Drive\Volumio Now Playing backups
set KEEP=20

if not exist "G:\My Drive\" (
    echo Could not find "G:\My Drive".
    echo Check Google Drive for desktop is running. If your Drive uses a
    echo different letter, edit the DEST line near the top of this file.
    echo.
    if not "%1"=="quiet" pause
    exit /b 1
)
if not exist "%DEST%\" mkdir "%DEST%"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set STAMP=%%i
set FILE=%DEST%\nowplaying-settings-%STAMP%.json

echo Downloading settings from Volumio...
curl.exe -f -s -S -m 20 -o "%FILE%" "http://%HOST%:%PORT%/settings/backup?keys=1"
if errorlevel 1 goto fail

rem An empty or tiny file means something went wrong on the way
for %%F in ("%FILE%") do if %%~zF LSS 20 goto fail

rem Keep only the newest %KEEP% backups
for /f "skip=%KEEP% delims=" %%F in ('dir /b /o-n "%DEST%\nowplaying-settings-*.json" 2^>nul') do del "%DEST%\%%F"

echo.
echo Done. Saved to:
echo   %FILE%
echo.
if not "%1"=="quiet" pause
exit /b 0

:fail
if exist "%FILE%" del "%FILE%"
echo.
echo The backup failed - see the message above.
echo Check the now-playing page is running at http://%HOST%:%PORT%
echo.
if not "%1"=="quiet" pause
exit /b 1
