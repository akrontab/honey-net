# Opens an interactive SSH session to a server.
# Default: port 65022 via Tailscale IP (post-setup).
# -PreSetup: port 22 via public IP (before setup.sh has run).

param(
    [string]$Server,
    [switch]$PreSetup,
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
connect.ps1 [-Server <name>] [-PreSetup] [-h]

Opens an SSH session to a server.

  Default    Port 65022 via Tailscale IP. Use after setup.sh has run.
  -PreSetup  Port 22 via public IP. Use before setup.sh runs (fresh server).

SERVERS (from honey-net.json)
$serverBlock

REQUIRES
  Default:   Tailscale running locally; state.json with tailscale_ip entries
  -PreSetup: state.json with public_ip entries (run sync-ips.ps1 after terraform apply)
"@
    exit 0
}

# Load state
if (-not (Test-Path $stateFile)) {
    Write-Error "state.json not found. Run sync-ips.ps1 after terraform apply."
    exit 1
}
$state = Get-Content $stateFile | ConvertFrom-Json

# Server selection
if (-not $Server) {
    Write-Host ""
    Write-Host "Select a server to connect to:"
    $i = 0
    foreach ($s in $servers) {
        $entry = if ($state.PSObject.Properties[$s.name]) { $state.$($s.name) } else { $null }
        if ($PreSetup) {
            $ipStr = if ($entry.public_ip) { $entry.public_ip } else { "(no public IP — run sync-ips.ps1)" }
        } else {
            $ipStr = if ($entry.tailscale_ip) { $entry.tailscale_ip } else { "(no Tailscale IP — run sync-ips.ps1)" }
        }
        $ports = if ($s.ports.Count) { $s.ports -join "," } else { "none" }
        Write-Host ("  [{0}] {1,-25} type={2,-10} ports={3,-10} ip={4}" -f $i, $s.name, $s.type, $ports, $ipStr)
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

$name   = $serverDef.name
$sshKey = ($serverDef.ssh_key -replace "^~", $env:USERPROFILE)
$entry  = if ($state.PSObject.Properties[$name]) { $state.$name } else { $null }

if ($PreSetup) {
    $ip = $entry.public_ip
    if ([string]::IsNullOrWhiteSpace($ip)) {
        Write-Error "No public IP for '$name' in state.json. Run sync-ips.ps1 after terraform apply."
        exit 1
    }
    Write-Host "Connecting to $name ($ip) on port 22 (pre-setup)..."
    ssh -i $sshKey -p 22 `
        -o StrictHostKeyChecking=no `
        -o UserKnownHostsFile=NUL `
        "root@${ip}"
} else {
    $ip = $entry.tailscale_ip
    if ([string]::IsNullOrWhiteSpace($ip)) {
        Write-Error "No Tailscale IP for '$name' in state.json. Run sync-ips.ps1 (Tailscale must be active)."
        Write-Host "  If this is a fresh server that hasn't run setup.sh yet, use: .\connect.ps1 -Server $name -PreSetup"
        exit 1
    }
    Write-Host "Connecting to $name ($ip) on port 65022..."
    ssh -i $sshKey -p 65022 `
        -o StrictHostKeyChecking=no `
        -o UserKnownHostsFile=NUL `
        "root@${ip}"
}
