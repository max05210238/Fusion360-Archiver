@echo off
REM ===========================================================================
REM  Fusion360 Archiver - Windows 一鍵啟動
REM  使用方式：對本檔點兩下即可。
REM  自動：找 Python → 建立隔離環境 → 裝套件 → 開伺服器 → 打開瀏覽器。
REM ===========================================================================
chcp 65001 >nul
cd /d "%~dp0route_b"

echo ===================================================
echo    Fusion360 Archiver 啟動中…
echo ===================================================

REM --- 1. 找 Python ---
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  找不到 Python，需要先安裝一次。已幫你打開下載頁。
  echo  安裝時請勾選 "Add Python to PATH"，裝完重新點兩下本檔。
  start "" "https://www.python.org/downloads/windows/"
  pause
  exit /b 1
)

REM --- 2. 建立 / 確認隔離環境 ---
if not exist ".venv\Scripts\python.exe" (
  echo 首次執行：建立隔離環境…
  python -m venv .venv
)
set "VENV_PY=.venv\Scripts\python.exe"

"%VENV_PY%" -c "import flask, requests" >nul 2>nul
if errorlevel 1 (
  echo 安裝必要套件（約 1 分鐘，只有第一次需要）…
  "%VENV_PY%" -m pip install --quiet --upgrade pip
  "%VENV_PY%" -m pip install --quiet -r requirements.txt
)

REM --- 3. 啟動 ---
echo.
echo  介面啟動中，瀏覽器會自動打開： http://localhost:8080
echo  要結束：關閉本視窗，或按 Ctrl+C
echo ---------------------------------------------------
"%VENV_PY%" app.py
pause
