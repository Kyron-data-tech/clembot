#!/usr/bin/env bash
# =============================================================================
# Clembot — macOS App & DMG Build Script (Apple Silicon arm64)
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "==> Building Clembot for macOS (Apple Silicon)..."
cd "$REPO_ROOT"

# Ensure PyInstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo "PyInstaller not found. Installing..."
    pip install pyinstaller
fi

# Clean previous builds
rm -rf build/ dist/

# Run PyInstaller
echo "==> Running PyInstaller with packaging/macos/clembot.spec..."
pyinstaller packaging/macos/clembot.spec --noconfirm

# Verify .app was generated
if [ -d "dist/Clembot.app" ]; then
    echo "==> Successfully created dist/Clembot.app"
    
    # Ad-hoc code sign for local execution if not using an Apple Developer Certificate
    echo "==> Applying ad-hoc signature to Clembot.app..."
    codesign --force --deep --sign - "dist/Clembot.app"

    # Optional: Build DMG image
    echo "==> Packaging dist/Clembot.dmg..."
    hdiutil create -volname "Clembot" -srcfolder "dist/Clembot.app" -ov -format UDZO "dist/Clembot.dmg"
    echo "==> DMG build complete: dist/Clembot.dmg"
else
    echo "Error: Clembot.app was not found in dist/"
    exit 1
fi
