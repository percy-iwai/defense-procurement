# Kit environment bootstrap (Windows PowerShell, ASCII-only for PS 5.1 compatibility)
# Usage:  powershell -ExecutionPolicy Bypass -File kit\setup_env.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "=== Checking Python ==="
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python not found. Install Python 3.10+ from https://www.python.org/"
    Write-Host "SUMMARY setup=FAIL reason=no_python"
    exit 1
}
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if ($LASTEXITCODE -ne 0) {
    python --version
    Write-Host "Python 3.10+ is required."
    Write-Host "SUMMARY setup=FAIL reason=python_too_old"
    exit 1
}
python --version

Write-Host "=== Creating venv ==="
if (-not (Test-Path "$root\.venv")) { python -m venv "$root\.venv" }
& "$root\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet

Write-Host "=== Installing dependencies ==="
& "$root\.venv\Scripts\python.exe" -m pip install -r "$root\kit\requirements_cpu.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Host "SUMMARY setup=FAIL reason=pip_install"
    exit 1
}

Write-Host "=== Smoke test ==="
& "$root\.venv\Scripts\python.exe" -c "import requests, pandas, openpyxl, bs4, pdfplumber, rapidfuzz, streamlit, plotly; print('imports OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "SUMMARY setup=FAIL reason=import_smoke"
    exit 1
}

Write-Host ""
Write-Host "SUMMARY setup=OK venv=$root\.venv"
Write-Host "Activate with: $root\.venv\Scripts\Activate.ps1"
Write-Host "Or run directly: $root\.venv\Scripts\python.exe kit\downloader.py ..."
