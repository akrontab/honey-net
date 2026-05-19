# Smoke-tests a running Cowrie deployment.
# Checks port 22/23 connectivity, SSH banner, container health, and log output.

param([int]$MgmtPort = 65022)

$root      = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$manifest  = Join-Path $root "honey-net.json"
$stateFile = Join-Path $root "state.json"

if (-not (Test-Path $manifest))  { Write-Error "honey-net.json not found at $root"; exit 1 }
if (-not (Test-Path $stateFile)) { Write-Error "state.json not found. Run sync-ips.ps1."; exit 1 }

$servers = Get-Content $manifest | ConvertFrom-Json
$state   = Get-Content $stateFile | ConvertFrom-Json

$candidates = @($servers | Where-Object { $_.honeypots -contains "cowrie" })
if ($candidates.Count -eq 0) { Write-Error "No cowrie servers in honey-net.json."; exit 1 }

if ($candidates.Count -eq 1) {
    $serverDef = $candidates[0]
} else {
    Write-Host ""
    Write-Host "Select a server to test:"
    $i = 0
    foreach ($s in $candidates) {
        $e     = if ($state.PSObject.Properties[$s.name]) { $state.$($s.name) } else { $null }
        $pubIp = if ($e.public_ip)    { $e.public_ip }    else { "(none)" }
        $tsIp  = if ($e.tailscale_ip) { $e.tailscale_ip } else { "(none)" }
        Write-Host ("  [{0}] {1,-20} public={2,-16} tailscale={3}" -f $i, $s.name, $pubIp, $tsIp)
        $i++
    }
    Write-Host ""
    $choice = Read-Host "Enter number"
    if ($choice -notmatch '^\d+$' -or [int]$choice -ge $candidates.Count) {
        Write-Error "Invalid selection."; exit 1
    }
    $serverDef = $candidates[[int]$choice]
}

$name   = $serverDef.name
$sshKey = ($serverDef.ssh_key -replace "^~", $env:USERPROFILE)
$entry  = if ($state.PSObject.Properties[$name]) { $state.$name } else { $null }
$pubIp  = $entry.public_ip
$tsIp   = $entry.tailscale_ip

if ([string]::IsNullOrWhiteSpace($pubIp)) {
    Write-Error "No public IP for '$name' in state.json. Run sync-ips.ps1 after terraform apply."
    exit 1
}

Write-Host ""
Write-Host "Testing: $name"
Write-Host "  Public IP   : $pubIp"
Write-Host "  Tailscale IP: $(if ($tsIp) { $tsIp } else { '(none — management tests will be skipped)' })"
Write-Host ""

$pass = 0; $fail = 0; $skip = 0

function Pass($msg) { Write-Host "  [PASS] $msg" -ForegroundColor Green;  $script:pass++ }
function Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red;    $script:fail++ }
function Skip($msg) { Write-Host "  [SKIP] $msg" -ForegroundColor Yellow; $script:skip++ }
function Info($msg) { Write-Host "         $msg" -ForegroundColor Gray }

# ── Test 1: Port 22 reachable ────────────────────────────────────────
Write-Host "[ 1 ] Port 22 reachable (honeypot SSH)"
$tcp = New-Object System.Net.Sockets.TcpClient
try {
    $tcp.ConnectAsync($pubIp, 22).Wait(3000) | Out-Null
    if ($tcp.Connected) { Pass "Port 22 is open" } else { Fail "Port 22 not reachable" }
} catch { Fail "Port 22 not reachable ($_)" } finally { $tcp.Close() }

# ── Test 2: SSH banner ────────────────────────────────────────────────
Write-Host ""
Write-Host "[ 2 ] SSH banner"
try {
    $client = New-Object System.Net.Sockets.TcpClient($pubIp, 22)
    $stream = $client.GetStream(); $stream.ReadTimeout = 3000
    $buf = New-Object byte[] 512
    $n   = $stream.Read($buf, 0, $buf.Length)
    $banner = [Text.Encoding]::ASCII.GetString($buf, 0, $n).Trim()
    $client.Close()
    Info "Banner: $banner"
    if ($banner -match "OpenSSH_8\.9p1 Ubuntu") { Pass "Banner matches expected fake AWS version" }
    else                                          { Fail "Banner does not match expected value" }
} catch { Fail "Could not read SSH banner ($_)" }

# ── Tests 3-5 require Tailscale ──────────────────────────────────────
if ([string]::IsNullOrWhiteSpace($tsIp)) {
    Write-Host ""
    Skip "Port $MgmtPort reachable — no Tailscale IP (run sync-ips.ps1 after setup.sh)"
    Skip "Container status — no Tailscale IP"
    Skip "Cowrie log file — no Tailscale IP"
} else {
    $sshArgs = @("-i", $sshKey, "-p", $MgmtPort, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL")

    # ── Test 3: Management port ───────────────────────────────────────
    Write-Host ""
    Write-Host "[ 3 ] Management port $MgmtPort reachable (Tailscale)"
    $tcp2 = New-Object System.Net.Sockets.TcpClient
    try {
        $tcp2.ConnectAsync($tsIp, $MgmtPort).Wait(3000) | Out-Null
        if ($tcp2.Connected) { Pass "Port $MgmtPort is open" }
        else                 { Fail "Port $MgmtPort not reachable — check UFW and Tailscale" }
    } catch { Fail "Port $MgmtPort not reachable ($_)" } finally { $tcp2.Close() }

    # ── Test 4: Container running ─────────────────────────────────────
    Write-Host ""
    Write-Host "[ 4 ] Cowrie container status"
    $status = ssh @sshArgs "root@${tsIp}" "docker ps --filter name=cowrie --format '{{.Status}}'" 2>$null
    if ($status -match "^Up") { Pass "Container is running ($status)" }
    else                       { Fail "Container not running (got: '$status')" }

    # ── Test 5: Log file ──────────────────────────────────────────────
    Write-Host ""
    Write-Host "[ 5 ] Cowrie JSON log"
    $logPath  = "/opt/$name/cowrie/volumes/var/log/cowrie/cowrie.json"
    $logCheck = ssh @sshArgs "root@${tsIp}" "wc -l < $logPath 2>/dev/null || echo MISSING" 2>$null
    if ($logCheck -eq "MISSING") {
        Fail "Log file not found at $logPath"
    } else {
        Pass "Log file exists ($logCheck lines)"
        Info "Last 3 events:"
        ssh @sshArgs "root@${tsIp}" "tail -3 $logPath" 2>$null | ForEach-Object { Info $_ }
    }
}

# ── Summary ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "────────────────────────────────────"
Write-Host "  $pass passed, $fail failed, $skip skipped"
Write-Host "────────────────────────────────────"
if ($fail -gt 0) { exit 1 }
