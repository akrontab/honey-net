# Pulls log files from a honeypot server to a local logs/<server-name>/ directory.
# Connects via Tailscale (port 65022). Only meaningful for honeypot servers.

param(
    [string]$Server,
    [switch]$h,
    [switch]$Help
)

$manifest  = Join-Path $PSScriptRoot "honey-net.json"
$stateFile = Join-Path $PSScriptRoot "state.json"

if (-not (Test-Path $manifest)) { Write-Error "honey-net.json not found."; exit 1 }
$servers = Get-Content $manifest | ConvertFrom-Json

# Log file paths on the server, keyed by honeypot package name
$logPaths = @{
    cowrie = "/opt/{0}/cowrie/volumes/var/log/cowrie/cowrie.json"
    mysql  = "/opt/{0}/mysql/volumes/logs/mysql-honeypot.json"
}

if ($h -or $Help) {
    $serverBlock = ($servers | ForEach-Object {
        $ports = if ($_.ports.Count) { $_.ports -join ", " } else { "none" }
        $hps   = if ($_.honeypots.Count) { $_.honeypots -join ", " } else { "-" }
        "  {0,-25} type={1,-10} ports={2,-12} honeypots={3}" -f $_.name, $_.type, $ports, $hps
    }) -join "`n"

    Write-Host @"
get-logs.ps1 [-Server <name>] [-h]

Pulls log files from a honeypot server to logs/<server-name>/ on your local machine.
Connects via Tailscale on port 65022.

LOG PATHS PULLED (per honeypot package)
  cowrie  /opt/<server>/cowrie/volumes/var/log/cowrie/cowrie.json
  mysql   /opt/<server>/mysql/volumes/logs/mysql-honeypot.json

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

# Only show honeypot servers in the menu
$honeypots = $servers | Where-Object { $_.type -eq "honeypot" }

# Server selection
if (-not $Server) {
    Write-Host ""
    Write-Host "Select a honeypot server to pull logs from:"
    $i = 0
    foreach ($s in $honeypots) {
        $tsIp  = if ($state.PSObject.Properties[$s.name]) { $state.$($s.name).tailscale_ip } else { $null }
        $ipStr = if ($tsIp) { $tsIp } else { "(no Tailscale IP — run sync-ips.ps1)" }
        $hps   = if ($s.honeypots.Count) { $s.honeypots -join ", " } else { "-" }
        Write-Host ("  [{0}] {1,-25} honeypots={2,-20} tailscale={3}" -f $i, $s.name, $hps, $ipStr)
        $i++
    }
    Write-Host ""
    $choice = Read-Host "Enter number"
    if ($choice -notmatch '^\d+$' -or [int]$choice -ge $honeypots.Count) {
        Write-Error "Invalid selection."
        exit 1
    }
    $serverDef = $honeypots[[int]$choice]
} else {
    $serverDef = $servers | Where-Object { $_.name -eq $Server }
    if (-not $serverDef) {
        Write-Error "Server '$Server' not found in honey-net.json."
        exit 1
    }
    if ($serverDef.type -ne "honeypot") {
        Write-Error "'$Server' is a $($serverDef.type) server. get-logs.ps1 only applies to honeypot servers."
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

$localDir = Join-Path $PSScriptRoot "logs\$name"
if (-not (Test-Path $localDir)) {
    New-Item -ItemType Directory -Path $localDir | Out-Null
}

Write-Host "Pulling logs from $name ($tailscaleIp)..."
Write-Host ""

$pulled = 0
$failed = 0

foreach ($hp in $serverDef.honeypots) {
    if (-not $logPaths.ContainsKey($hp)) {
        Write-Warning "No known log path for honeypot type '$hp' — skipping."
        continue
    }
    $remotePath = $logPaths[$hp] -f $name
    $localFile  = Join-Path $localDir "$hp.json"

    Write-Host "  $hp -> $localFile"
    scp -P 65022 -i $sshKey `
        -o StrictHostKeyChecking=no `
        -o UserKnownHostsFile=NUL `
        "root@${tailscaleIp}:${remotePath}" `
        $localFile

    if ($LASTEXITCODE -eq 0) {
        $lines = (Get-Content $localFile | Measure-Object -Line).Lines
        Write-Host "    $lines events"
        $pulled++
    } else {
        Write-Warning "    Failed (scp exit $LASTEXITCODE) — log file may not exist yet."
        $failed++
    }
}

Write-Host ""
if ($pulled -gt 0) {
    Write-Host "Logs saved to logs\$name\"
}
if ($failed -gt 0) {
    Write-Host "$failed log(s) could not be pulled."
}
