# Opens a raw TCP connection to port 3306 and reads the MySQL server greeting.
# A valid greeting confirms the honeypot is running and speaking MySQL protocol.

param([int]$Port = 3306)

$root      = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$manifest  = Join-Path $root "honey-net.json"
$stateFile = Join-Path $root "state.json"

if (-not (Test-Path $manifest))  { Write-Error "honey-net.json not found at $root"; exit 1 }
if (-not (Test-Path $stateFile)) { Write-Error "state.json not found. Run sync-ips.ps1."; exit 1 }

$servers = Get-Content $manifest | ConvertFrom-Json
$state   = Get-Content $stateFile | ConvertFrom-Json

$candidates = @($servers | Where-Object { $_.honeypots -contains "mysql" })
if ($candidates.Count -eq 0) { Write-Error "No mysql servers in honey-net.json."; exit 1 }

if ($candidates.Count -eq 1) {
    $serverDef = $candidates[0]
} else {
    Write-Host ""
    Write-Host "Select a server to test:"
    $i = 0
    foreach ($s in $candidates) {
        $e     = if ($state.PSObject.Properties[$s.name]) { $state.$($s.name) } else { $null }
        $pubIp = if ($e.public_ip) { $e.public_ip } else { "(none)" }
        Write-Host ("  [{0}] {1,-20} public={2}" -f $i, $s.name, $pubIp)
        $i++
    }
    Write-Host ""
    $choice = Read-Host "Enter number"
    if ($choice -notmatch '^\d+$' -or [int]$choice -ge $candidates.Count) {
        Write-Error "Invalid selection."; exit 1
    }
    $serverDef = $candidates[[int]$choice]
}

$name  = $serverDef.name
$entry = if ($state.PSObject.Properties[$name]) { $state.$name } else { $null }
$ip    = $entry.public_ip

if ([string]::IsNullOrWhiteSpace($ip)) {
    Write-Error "No public IP for '$name' in state.json. Run sync-ips.ps1 after terraform apply."
    exit 1
}

Write-Host "Connecting to ${ip}:${Port} ($name)..."
$tcp = New-Object System.Net.Sockets.TcpClient
try {
    $tcp.Connect($ip, $Port)
    if ($tcp.Connected) {
        $stream = $tcp.GetStream(); $stream.ReadTimeout = 3000
        $buf  = New-Object byte[] 512
        $read = $stream.Read($buf, 0, $buf.Length)
        if ($read -gt 5) {
            $versionBytes = $buf[5..([Math]::Min($read - 1, 30))]
            $version = [System.Text.Encoding]::ASCII.GetString($versionBytes).Split([char]0)[0]
            Write-Host "OK — server greeted with MySQL $version"
        } else {
            Write-Host "Connected but received unexpected response ($read bytes)."
        }
    }
} catch {
    Write-Warning "Connection failed: $_"
} finally {
    $tcp.Close()
}
