# Opens an interactive SSH session to a server via Tailscale (port 65022).
# Requires Tailscale running locally and state.json with tailscale_ip entries.

param(
    [string]$Server,
    [switch]$h,
    [switch]$Help
)

$manifest  = Join-Path $PSScriptRoot "honey-net.json"
$stateFile = Join-Path $PSScriptRoot "state.json"

if (-not (Test-Path $manifest)) { Write-Error "honey-net.json not found."; exit 1 }
$servers = Get-Content $manifest | ConvertFrom-Json

if ($h -or $Help) {
    $serverBlock = ($servers | ForEach-Object {
        $ports = if ($_.ports.Count) { $_.ports -join ", " } else { "none" }
        $hps   = if ($_.honeypots.Count) { $_.honeypots -join ", " } else { "-" }
        "  {0,-25} type={1,-10} ports={2,-12} honeypots={3}" -f $_.name, $_.type, $ports, $hps
    }) -join "`n"

    Write-Host @"
connect.ps1 [-Server <name>] [-h]

Opens an SSH session to a server on port 65022 via its Tailscale IP.
The server must have been provisioned with deploy.ps1 and setup.sh.

SERVERS (from honey-net.json)
$serverBlock

REQUIRES
  Tailscale running locally
  state.json with tailscale_ip entries (run sync-ips.ps1 after servers join Tailscale)
"@
    exit 0
}

# Load state
if (-not (Test-Path $stateFile)) {
    Write-Error "state.json not found. Run sync-ips.ps1."
    exit 1
}
$state = Get-Content $stateFile | ConvertFrom-Json

# Server selection
if (-not $Server) {
    Write-Host ""
    Write-Host "Select a server to connect to:"
    $i = 0
    foreach ($s in $servers) {
        $tsIp  = if ($state.PSObject.Properties[$s.name]) { $state.$($s.name).tailscale_ip } else { $null }
        $ipStr = if ($tsIp) { $tsIp } else { "(no Tailscale IP — run sync-ips.ps1)" }
        $ports = if ($s.ports.Count) { $s.ports -join "," } else { "none" }
        Write-Host ("  [{0}] {1,-25} type={2,-10} ports={3,-10} tailscale={4}" -f $i, $s.name, $s.type, $ports, $ipStr)
        $i++
    }
    Write-Host ""
    $choice = Read-Host "Enter number"
    if ($choice -notmatch '^\d+$' -or [int]$choice -ge $servers.Count) {
        Write-Error "Invalid selection."
        exit 1
    }
    $serverDef = $servers[[int]$choice]
} else {
    $serverDef = $servers | Where-Object { $_.name -eq $Server }
    if (-not $serverDef) {
        Write-Error "Server '$Server' not found in honey-net.json."
        exit 1
    }
}

$name        = $serverDef.name
$sshKey      = ($serverDef.ssh_key -replace "^~", $env:USERPROFILE)
$tailscaleIp = if ($state.PSObject.Properties[$name]) { $state.$name.tailscale_ip } else { $null }

if ([string]::IsNullOrWhiteSpace($tailscaleIp)) {
    Write-Error "No Tailscale IP for '$name' in state.json. Run sync-ips.ps1 (Tailscale must be active)."
    exit 1
}

Write-Host "Connecting to $name ($tailscaleIp) on port 65022..."
ssh -i $sshKey -p 65022 `
    -o StrictHostKeyChecking=no `
    -o UserKnownHostsFile=NUL `
    "root@${tailscaleIp}"
