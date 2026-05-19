# Reads Terraform outputs and Tailscale device IPs, writes state.json.
# Run after `terraform apply`. Re-run after servers join Tailscale to capture Tailscale IPs.

param([switch]$h, [switch]$Help)

if ($h -or $Help) {
    $servers = Get-Content (Join-Path $PSScriptRoot "honey-net.json") | ConvertFrom-Json
    $serverBlock = ($servers | ForEach-Object {
        $ports = if ($_.ports.Count) { $_.ports -join ", " } else { "none" }
        "  {0,-25} type={1,-10} ports={2}" -f $_.name, $_.type, $ports
    }) -join "`n"

    Write-Host @"
sync-ips.ps1

Reads public IPs from Terraform output, looks up Tailscale IPs via the Tailscale
API, and writes state.json at the honey-net root.

USAGE
  .\sync-ips.ps1

REQUIRES
  terraform apply has been run
  ~/.tailscale-apikey    Tailscale API key for Tailscale IP lookups (Settings -> Keys -> API keys)

SERVERS (from honey-net.json)
$serverBlock

NOTES
  state.json is gitignored. All root scripts read server IPs from it.
  Re-run after servers join Tailscale to populate tailscale_ip entries.
  Tailscale IPs are looked up by matching server name to Tailscale device hostname.
"@
    exit 0
}

$tfDir     = Join-Path $PSScriptRoot "terraform"
$manifest  = Join-Path $PSScriptRoot "honey-net.json"
$stateFile = Join-Path $PSScriptRoot "state.json"
$tsKeyFile = Join-Path $env:USERPROFILE ".tailscale-apikey"

if (-not (Test-Path (Join-Path $tfDir ".terraform"))) {
    Write-Error "Terraform not initialised. Run: cd terraform && terraform init"
    exit 1
}

if (-not (Test-Path $manifest)) {
    Write-Error "honey-net.json not found."
    exit 1
}

$servers = Get-Content $manifest | ConvertFrom-Json

# --- Public IPs from Terraform ---
Write-Host "Reading terraform outputs..."
$raw = terraform "-chdir=$tfDir" output -json
if ($LASTEXITCODE -ne 0) {
    Write-Error "terraform output failed — has terraform apply been run?"
    exit 1
}

if ([string]::IsNullOrWhiteSpace($raw) -or $raw.Trim() -eq '{}') {
    Write-Error "terraform output returned no values. Run terraform apply first."
    exit 1
}

$outputs   = $raw | ConvertFrom-Json
$publicIps = $outputs.server_ips.value

# --- Tailscale IPs via API ---
$tsDevices = @{}
if (Test-Path $tsKeyFile) {
    $tsKey = (Get-Content $tsKeyFile -Raw).Trim()
    try {
        $resp = Invoke-RestMethod `
            -Uri "https://api.tailscale.com/api/v2/tailnet/-/devices" `
            -Headers @{ Authorization = "Bearer $tsKey" } `
            -ErrorAction Stop
        foreach ($device in $resp.devices) {
            $tsIp = $device.addresses | Where-Object { $_ -like "100.*" } | Select-Object -First 1
            if ($tsIp) { $tsDevices[$device.hostname] = $tsIp }
        }
        Write-Host "Tailscale: $($tsDevices.Count) device(s) found in tailnet"
    } catch {
        Write-Warning "Tailscale API call failed — Tailscale IPs will be null."
        Write-Warning $_
    }
} else {
    Write-Warning "~/.tailscale-apikey not found — Tailscale IPs will be null."
    Write-Warning "Generate one at tailscale.com -> Settings -> Keys -> Generate API key"
}

# --- Build state.json ---
$state = [ordered]@{}
foreach ($server in $servers) {
    $name     = $server.name
    $publicIp = $publicIps.$name

    if ([string]::IsNullOrWhiteSpace($publicIp)) {
        Write-Warning "No terraform output for '$name' — skipping (add it to honey-net.json and re-apply)"
        continue
    }

    $tsIp      = $tsDevices[$name]
    $tsDisplay = if ($tsIp) { $tsIp } else { "(not in tailnet yet)" }

    $state[$name] = [ordered]@{
        public_ip    = $publicIp
        tailscale_ip = $tsIp
    }

    Write-Host ("  {0,-25} public={1,-16} tailscale={2}" -f $name, $publicIp, $tsDisplay)
}

$state | ConvertTo-Json -Depth 3 | Set-Content $stateFile -Encoding UTF8

Write-Host ""
Write-Host "state.json written."
if ($tsDevices.Count -eq 0) {
    Write-Host "Re-run after servers have joined Tailscale to populate tailscale_ip entries."
}
