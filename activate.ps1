# Activates .venv in the current PowerShell session.

# pwsh on macOS and Linux gets bin/; Windows gets Scripts\.
$activate = @(
    (Join-Path $PSScriptRoot ".venv/Scripts/Activate.ps1"),
    (Join-Path $PSScriptRoot ".venv/bin/Activate.ps1")
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $activate) {
    Write-Error ".venv not found. Run .\setup.ps1 first."
    return
}

& $activate
