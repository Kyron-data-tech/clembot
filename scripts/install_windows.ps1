# =============================================================================
# Clembot — Windows Automated Environment Setup Script
# Creates a virtual environment, installs Windows dependencies, and audits health.
# =============================================================================

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "       CLEMBOT — Windows 10/11 Automated Installation           " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# 1. Verify OS
if ($PSVersionTable.Platform -and $PSVersionTable.Platform -ne "Win32NT") {
    Write-Host "[ERROR] This installer is meant for Windows 10/11 only." -ForegroundColor Red
    Write-Host "For macOS, please run: bash scripts/install_macos.sh" -ForegroundColor Yellow
    exit 1
}

# 2. Check Python availability
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "[ERROR] Python 3.10+ was not found in PATH." -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org/downloads/ and check 'Add to PATH'." -ForegroundColor Yellow
    exit 1
}

$pyVer = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "[INFO] Detected Python $pyVer" -ForegroundColor Green

# 3. Create Virtual Environment
if (-not (Test-Path "venv\Scripts\Activate.ps1")) {
    Write-Host "[INFO] Creating virtual environment in .\venv..." -ForegroundColor Cyan
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[INFO] Virtual environment already exists." -ForegroundColor Green
}

# 4. Activate Virtual Environment
Write-Host "[INFO] Activating virtual environment..." -ForegroundColor Cyan
& ".\venv\Scripts\Activate.ps1"

# 5. Upgrade pip and install Windows dependencies
Write-Host "[INFO] Upgrading pip..." -ForegroundColor Cyan
.\venv\Scripts\python.exe -m pip install --upgrade pip --quiet

Write-Host "[INFO] Installing Windows dependencies from requirements/windows.txt..." -ForegroundColor Cyan
.\venv\Scripts\python.exe -m pip install -r requirements/windows.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Dependency installation encountered errors." -ForegroundColor Red
    exit 1
}

# 6. Verify Installation via SystemDoctor
Write-Host "`n[INFO] Running System Doctor pre-flight diagnostic..." -ForegroundColor Cyan
.\venv\Scripts\python.exe app\doctor.py

Write-Host "`n=================================================================" -ForegroundColor Green
Write-Host "  INSTALLATION COMPLETE! To run Clembot:" -ForegroundColor Green
Write-Host "    .\run_clembot.bat  OR  .\venv\Scripts\python.exe -m app.main" -ForegroundColor Yellow
Write-Host "=================================================================" -ForegroundColor Green
