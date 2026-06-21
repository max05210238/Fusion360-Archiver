#!/bin/bash
# =============================================================================
#  Fusion360 Archiver — macOS 一鍵啟動
#  使用方式：在 Finder 對本檔點兩下即可（第一次若被擋，右鍵 ▸ 打開）。
#  它會自動：找 Python3 → 建立隔離環境 → 裝套件 → 開伺服器 → 打開瀏覽器。
# =============================================================================
cd "$(cd "$(dirname "$0")" && pwd)/route_b" || exit 1

echo "==================================================="
echo "   Fusion360 Archiver 啟動中…"
echo "==================================================="

# --- 1. 找 Python 3 ---
PY=""
for c in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo ""
  echo "⚠️  找不到 Python 3，需要先安裝一次。"
  echo "    已幫你打開下載頁，安裝後重新點兩下本檔即可。"
  open "https://www.python.org/downloads/macos/" 2>/dev/null
  read -r -p "（按 Enter 關閉本視窗）" _
  exit 1
fi
echo "使用 Python：$("$PY" --version 2>&1)"

# --- 2. 建立 / 確認隔離環境（避免污染系統、繞開套件衝突）---
if [ ! -d ".venv" ]; then
  echo "首次執行：建立隔離環境…"
  "$PY" -m venv .venv || { echo "建立環境失敗"; read -r -p "按 Enter 關閉" _; exit 1; }
fi
VENV_PY="./.venv/bin/python"

# 套件不齊就（重新）安裝
if ! "$VENV_PY" -c "import flask, requests" >/dev/null 2>&1; then
  echo "安裝必要套件（約 1 分鐘，只有第一次需要）…"
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -r requirements.txt || {
    echo "套件安裝失敗，請把上面訊息回報。"; read -r -p "按 Enter 關閉" _; exit 1; }
fi

# --- 3. 啟動 ---
echo ""
echo "✅ 介面啟動中，瀏覽器會自動打開： http://localhost:8080"
echo "   要結束：關閉本視窗，或按 Ctrl+C"
echo "---------------------------------------------------"
exec "$VENV_PY" app.py
