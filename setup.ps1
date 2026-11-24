# Game Dev OS - one-step local setup for Windows (PowerShell).
# Usage:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Creates .venv (if missing), upgrades pip, installs requirements.txt,
# and checks that the app imports cleanly.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvDir = ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

# 1. Find a Python 3.10+ interpreter (prefer the py launcher).
function Find-Python {
    foreach ($candidate in @("py -3", "python", "python3")) {
        $parts = $candidate.Split(" ")
        $exe = $parts[0]
        $exeArgs = @($parts | Select-Object -Skip 1)
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            $ver = & $exe @exeArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver -and [version]$ver -ge [version]"3.10") {
                return ,$parts
            }
        }
    }
    return $null
}

if (-not (Test-Path $venvPython)) {
    $python = Find-Python
    if ($null -eq $python) {
        Write-Error "Python 3.10+ not found. Install it from https://www.python.org/downloads/ and re-run."
    }
    Write-Host "Creating virtual environment in $venvDir ..."
    $exe = $python[0]
    $pyArgs = @($python | Select-Object -Skip 1)
    & $exe @pyArgs -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create virtual environment." }
} else {
    Write-Host "Using existing virtual environment in $venvDir"
}

# 2. Install dependencies.
Write-Host "Upgrading pip ..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Error "pip upgrade failed." }

Write-Host "Installing requirements.txt (rembg/onnxruntime are large; this can take a few minutes) ..."
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Error "Dependency install failed." }

# 3. Sanity check.
Write-Host "Verifying install ..."
& $venvPython -c "import flask, cv2, numpy, requests, imageio_ffmpeg, rembg; import app; print('All packages OK')"
if ($LASTEXITCODE -ne 0) { Write-Error "Verification failed - see the error above." }

Write-Host ""
Write-Host "Setup complete. To start the app:"
Write-Host "  .venv\Scripts\Activate.ps1"
Write-Host "  python app.py"
Write-Host "Then open http://localhost:5000"
