@echo off
REM ===========================================================================
REM  Fusion360 Archiver - one-click launcher for Windows
REM  How to use: double-click this file.
REM  Automatically: finds Python -> creates an isolated environment ->
REM  installs packages -> starts the server -> opens your browser.
REM ===========================================================================
chcp 65001 >nul
cd /d "%~dp0route_b"

echo ===================================================
echo    Starting Fusion360 Archiver...
echo ===================================================

REM --- 1. Find Python ---
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Python was not found; it needs to be installed once. The download page has been opened.
  echo  During install, check "Add Python to PATH", then double-click this file again.
  start "" "https://www.python.org/downloads/windows/"
  pause
  exit /b 1
)

REM --- 2. Create / confirm the isolated environment ---
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating an isolated environment...
  python -m venv .venv
)
set "VENV_PY=.venv\Scripts\python.exe"

"%VENV_PY%" -c "import flask, requests" >nul 2>nul
if errorlevel 1 (
  echo Installing required packages (about 1 minute, only the first time)...
  "%VENV_PY%" -m pip install --quiet --upgrade pip
  "%VENV_PY%" -m pip install --quiet -r requirements.txt
)

REM --- 3. Start ---
echo.
echo  The interface is starting; your browser will open automatically: http://localhost:8080
echo  To stop: close this window, or press Ctrl+C
echo ---------------------------------------------------
"%VENV_PY%" app.py
pause
