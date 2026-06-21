#!/bin/bash
# =============================================================================
#  Fusion360 Archiver — one-click launcher for macOS
#  How to use: double-click this file in Finder (the first time, if it's blocked,
#  right-click > Open). It automatically: finds Python3 -> creates an isolated
#  environment -> installs packages -> starts the server -> opens your browser.
# =============================================================================
cd "$(cd "$(dirname "$0")" && pwd)/route_b" || exit 1

echo "==================================================="
echo "   Starting Fusion360 Archiver..."
echo "==================================================="

# --- 1. Find Python 3 ---
PY=""
for c in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo ""
  echo "Python 3 was not found; it needs to be installed once."
  echo "The download page has been opened for you. After installing, double-click this file again."
  open "https://www.python.org/downloads/macos/" 2>/dev/null
  read -r -p "(Press Enter to close this window)" _
  exit 1
fi
echo "Using Python: $("$PY" --version 2>&1)"

# --- 2. Create / confirm the isolated environment (avoids polluting the system, sidesteps package conflicts) ---
if [ ! -d ".venv" ]; then
  echo "First run: creating an isolated environment..."
  "$PY" -m venv .venv || { echo "Failed to create the environment"; read -r -p "Press Enter to close" _; exit 1; }
fi
VENV_PY="./.venv/bin/python"

# (Re)install if packages are missing
if ! "$VENV_PY" -c "import flask, requests" >/dev/null 2>&1; then
  echo "Installing required packages (about 1 minute, only the first time)..."
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -r requirements.txt || {
    echo "Package install failed; please report the message above."; read -r -p "Press Enter to close" _; exit 1; }
fi

# --- 3. Start ---
echo ""
echo "The interface is starting; your browser will open automatically: http://localhost:8080"
echo "To stop: close this window, or press Ctrl+C"
echo "---------------------------------------------------"
exec "$VENV_PY" app.py
