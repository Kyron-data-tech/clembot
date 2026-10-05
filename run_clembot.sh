#!/bin/bash
# =============================================================================
# Clembot — macOS Application Launcher
# Compatible with macOS (Apple Silicon arm64 / Intel).
# =============================================================================

set -e

# Change directory to script folder
cd "$(dirname "$0")"

echo "============================================================"
echo "  Starting Clembot — Cross-Platform Voice Assistant (macOS)"
echo "============================================================"

# Activate virtualenv if present
if [ -f "venv/bin/activate" ]; then
    echo "[INFO] Activating virtual environment..."
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    echo "[INFO] Activating virtual environment..."
    source .venv/bin/activate
fi

# Diagnostic mode check
if [ "$1" == "--doctor" ] || [ "$1" == "doctor" ]; then
    python app/doctor.py
    exit 0
fi

# Check requirements on first run
if [ ! -f ".deps_installed" ] && [ -f "requirements/macos.txt" ]; then
    echo "[INFO] Installing macOS dependencies on first run..."
    pip install -r requirements/macos.txt
    touch .deps_installed
fi

# Launch Clembot
echo "[INFO] Launching Clembot GUI and background services..."
python -m app.main
