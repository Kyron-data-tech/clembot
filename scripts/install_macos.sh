#!/bin/bash
# =============================================================================
# Clembot — macOS Automated Environment Setup Script
# Designed for Apple Silicon (M1/M2/M3/M4 arm64) & Intel Macs.
# =============================================================================

set -e

echo "================================================================="
echo "       CLEMBOT — macOS Native Automated Installation            "
echo "================================================================="

# 1. Verify OS is Darwin / macOS
OS="$(uname -s)"
if [ "$OS" != "Darwin" ]; then
    echo "[ERROR] This installer is meant for macOS only (detected: $OS)."
    echo "For Windows 10/11, please run: powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1"
    exit 1
fi

ARCH="$(uname -m)"
echo "[INFO] Detected macOS architecture: $ARCH"
if [ "$ARCH" = "arm64" ]; then
    echo "[INFO] Running on Apple Silicon (M-Series Mac)."
fi

# 2. Check for Python 3.10+
PYTHON_BIN=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PY_VER="$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        MAJOR="$($cmd -c 'import sys; print(sys.version_info.major)')"
        MINOR="$($cmd -c 'import sys; print(sys.version_info.minor)')"
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]; then
            PYTHON_BIN="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "[ERROR] Python 3.10+ was not found on your system."
    echo "Please install Python using Homebrew: brew install python@3.12"
    exit 1
fi

echo "[INFO] Using Python: $PYTHON_BIN ($($PYTHON_BIN --version))"

# 3. Check for Homebrew and PortAudio (for audio input/microphone)
if ! command -v brew >/dev/null 2>&1; then
    echo "[WARN] Homebrew is not installed. If audio recording fails, install Homebrew from https://brew.sh"
else
    if ! brew list portaudio >/dev/null 2>&1; then
        echo "[INFO] Installing PortAudio via Homebrew for microphone input..."
        brew install portaudio || echo "[WARN] Failed to install PortAudio via Homebrew; continuing..."
    else
        echo "[INFO] PortAudio is already installed via Homebrew."
    fi
fi

# 4. Create Virtual Environment
if [ ! -f "venv/bin/activate" ]; then
    echo "[INFO] Creating virtual environment in ./venv..."
    "$PYTHON_BIN" -m venv venv
else
    echo "[INFO] Virtual environment already exists."
fi

# 5. Activate Virtual Environment
echo "[INFO] Activating virtual environment..."
source venv/bin/activate

# 6. Upgrade pip and install macOS dependencies
echo "[INFO] Upgrading pip..."
pip install --upgrade pip --quiet

echo "[INFO] Installing macOS dependencies from requirements/macos.txt..."
pip install -r requirements/macos.txt

# 7. Run Pre-flight Diagnostic Doctor
echo ""
echo "[INFO] Running System Doctor pre-flight diagnostic..."
python app/doctor.py || true

# 8. Permissions Check & Summary
echo ""
echo "================================================================="
echo "  INSTALLATION COMPLETE!"
echo ""
echo "  IMPORTANT FIRST-TIME macOS PERMISSIONS SETUP:"
echo "  Clembot needs the following permissions in:"
echo "    System Settings -> Privacy & Security"
echo "      1. Microphone      (to hear your voice)"
echo "      2. Accessibility   (to switch windows and type shortcuts)"
echo "      3. Automation      (to control Chrome and Brave tabs)"
echo ""
echo "  To launch Clembot on macOS:"
echo "    ./run_clembot.sh   OR   ./venv/bin/python -m app.main"
echo "================================================================="
