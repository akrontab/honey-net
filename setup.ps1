# Creates .venv and installs honey-net Python dependencies.

$ErrorActionPreference = "Stop"

$minMajor = 3; $minMinor = 10

$ver = & python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python not found. Install Python $minMajor.$minMinor+ and try again."
    exit 1
}

if ($ver -match 'Python (\d+)\.(\d+)') {
    $major = [int]$Matches[1]; $minor = [int]$Matches[2]
    if ($major -lt $minMajor -or ($major -eq $minMajor -and $minor -lt $minMinor)) {
        Write-Error "Python $minMajor.$minMinor+ required — got $ver"
        exit 1
    }
} else {
    Write-Error "Could not parse Python version: $ver"
    exit 1
}

$venv = Join-Path $PSScriptRoot ".venv"

if (-not (Test-Path $venv)) {
    Write-Host "Creating .venv ..."
    python -m venv $venv
} else {
    Write-Host ".venv already exists"
}

Write-Host "Installing dependencies ..."
& "$venv\Scripts\pip.exe" install -r (Join-Path $PSScriptRoot "requirements.txt") --quiet

Write-Host @"

Done.

Activate the environment:
  .venv\Scripts\activate

Then run any script:
  python deploy.py --help
  python connect.py --help
  python sync_ips.py
"@
