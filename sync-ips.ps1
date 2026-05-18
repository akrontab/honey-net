# Reads Terraform outputs and writes each host's IP to its repo's .server-ip cache.
# Run this after `terraform apply` so deploy.ps1 and connect.ps1 work without prompting.

$tfDir = Join-Path $PSScriptRoot "terraform"

if (-not (Test-Path (Join-Path $tfDir ".terraform"))) {
    Write-Error "Terraform has not been initialised. Run: cd terraform && terraform init"
    exit 1
}

# Capture stdout only — stderr (warnings) goes to console and must not mix into the JSON
$raw = terraform "-chdir=$tfDir" output -json
if ($LASTEXITCODE -ne 0) {
    Write-Error "terraform output failed — has terraform apply been run?"
    exit 1
}

if ([string]::IsNullOrWhiteSpace($raw) -or $raw.Trim() -eq '{}') {
    Write-Error "terraform output returned no values. Run terraform apply first."
    exit 1
}

try {
    $outputs = $raw | ConvertFrom-Json
} catch {
    Write-Error "Failed to parse terraform output as JSON."
    Write-Host "Raw output was:"
    Write-Host $raw
    exit 1
}

$logStackIp = $outputs.log_stack_ip.value
$cowrieIp   = $outputs.cowrie_ip.value

if ([string]::IsNullOrWhiteSpace($logStackIp) -or [string]::IsNullOrWhiteSpace($cowrieIp)) {
    Write-Error "One or more IPs are missing from terraform output."
    Write-Host "Raw output was:"
    Write-Host $raw
    exit 1
}

$logStackIp | Set-Content (Join-Path $PSScriptRoot "log-stack\.server-ip") -NoNewline
$cowrieIp   | Set-Content (Join-Path $PSScriptRoot "cowrie-honeypot\.server-ip") -NoNewline

Write-Host ""
Write-Host "log-stack       : $logStackIp"
Write-Host "cowrie-honeypot : $cowrieIp"
Write-Host ""
Write-Host "IPs cached — deploy.ps1 and connect.ps1 are ready to use."
