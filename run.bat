@echo off
title Passport Slot Checker - Setup & Run
color 0A
cls

echo.
echo =====================================================
echo    PASSPORT SEVA - Slot Checker
echo    Setting up and starting...
echo =====================================================
echo.

:: ── STEP 1: Check if Python is installed ─────────────────────────────────────
echo [1/4] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  Python is NOT installed on this computer.
    echo  Opening Python download page in your browser...
    echo.
    echo  -----------------------------------------------
    echo  IMPORTANT - When the installer opens:
    echo    Check the box "Add Python to PATH"
    echo    Then click "Install Now"
    echo  -----------------------------------------------
    echo.
    start https://www.python.org/downloads/
    echo  After Python is installed, close this window
    echo  and double-click run.bat again.
    echo.
    pause
    exit /b
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo  Found: %PYVER%
echo.

:: ── STEP 2: Check / install pip packages ─────────────────────────────────────
echo [2/4] Checking required packages...
echo.

python -c "import playwright" >nul 2>&1
if %errorlevel% neq 0 (
    echo  Installing playwright - please wait...
    pip install playwright >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo  ERROR: Could not install playwright.
        echo  Please check your internet connection and try again.
        pause
        exit /b
    )
    echo  playwright installed OK
) else (
    echo  playwright already installed OK
)

:: ── STEP 3: Check / install Chromium browser ─────────────────────────────────
echo.
echo [3/4] Checking Chromium browser for automation...

set CHROMIUM_FLAG=%USERPROFILE%\.cache\ms-playwright\chromium_installed.flag

python -c "
from playwright.sync_api import sync_playwright
try:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        b.close()
    print('ok')
except:
    print('missing')
" > %TEMP%\pw_check.txt 2>&1

findstr /C:"ok" %TEMP%\pw_check.txt >nul 2>&1
if %errorlevel% neq 0 (
    echo  Installing Chromium browser - this may take a few minutes...
    playwright install chromium
    if %errorlevel% neq 0 (
        echo.
        echo  ERROR: Could not install Chromium.
        echo  Please check your internet connection and try again.
        pause
        exit /b
    )
    echo  Chromium installed OK
) else (
    echo  Chromium already installed OK
)

del %TEMP%\pw_check.txt >nul 2>&1

:: ── STEP 4: Check that check_slots.py exists ─────────────────────────────────
echo.
echo [4/4] Checking script file...

if not exist "%~dp0check_slots.py" (
    echo.
    echo  ERROR: check_slots.py not found!
    echo  Make sure check_slots.py is in the same folder as run.bat
    echo.
    pause
    exit /b
)
echo  check_slots.py found OK

:: ── All good — launch the script ─────────────────────────────────────────────
echo.
echo =====================================================
echo    All checks passed! Starting Passport Checker...
echo =====================================================
echo.
echo  A browser window will open automatically.
echo  DO NOT close this black window while the script runs.
echo  To stop the script press Ctrl+C in this window.
echo.
timeout /t 3 /nobreak >nul

cd /d "%~dp0"
python check_slots.py

echo.
echo  Script has stopped.
pause
