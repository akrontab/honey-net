# Smoke-tests a running Cowrie deployment.
# Checks port 22 connectivity, SSH banner, container health, and log output.

param(
    [string]$User         = "root",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\cowrie-linode",
    [int]$MgmtPort        = 65022
)

$cache = Join-Path $PSScriptRoot ".server-ip"

if (Test-Path $cache) {
    $ip = (Get-Content $cache).Trim()
} else {
    $ip = (Read-Host "Server IP address").Trim()
    if ([string]::IsNullOrWhiteSpace($ip)) {
        Write-Error "IP address is required."
        exit 1
    }
    $ip | Set-Content $cache
}

$pass = 0
$fail = 0

function Pass($msg) { Write-Host "  [PASS] $msg" -ForegroundColor Green;  $script:pass++ }
function Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red;    $script:fail++ }
function Info($msg) { Write-Host "         $msg" -ForegroundColor Gray }

# ── Test 1: Port 22 is open ──────────────────────────────────────────
Write-Host ""
Write-Host "[ 1 ] Port 22 reachable"
$tcp = New-Object System.Net.Sockets.TcpClient
try {
    $tcp.ConnectAsync($ip, 22).Wait(3000) | Out-Null
    if ($tcp.Connected) { Pass "Port 22 is open" }
    else                { Fail "Port 22 not reachable" }
} catch {
    Fail "Port 22 not reachable ($_)"
} finally {
    $tcp.Close()
}

# ── Test 2: SSH banner looks like our fake AWS instance ──────────────
Write-Host ""
Write-Host "[ 2 ] SSH banner"
try {
    $client = New-Object System.Net.Sockets.TcpClient($ip, 22)
    $stream = $client.GetStream()
    $stream.ReadTimeout = 3000
    $buf = New-Object byte[] 512
    $n   = $stream.Read($buf, 0, $buf.Length)
    $banner = [Text.Encoding]::ASCII.GetString($buf, 0, $n).Trim()
    $client.Close()

    Info "Banner: $banner"

    if ($banner -match "OpenSSH_8\.9p1 Ubuntu") { Pass "Banner matches expected fake AWS version" }
    else                                         { Fail "Banner does not match expected value" }
} catch {
    Fail "Could not read SSH banner ($_)"
}

# ── Test 3: Management port 65022 is open ───────────────────────────
Write-Host ""
Write-Host "[ 3 ] Management port $MgmtPort reachable"
$tcp2 = New-Object System.Net.Sockets.TcpClient
try {
    $tcp2.ConnectAsync($ip, $MgmtPort).Wait(3000) | Out-Null
    if ($tcp2.Connected) { Pass "Port $MgmtPort is open" }
    else                 { Fail "Port $MgmtPort not reachable — check UFW and sshd" }
} catch {
    Fail "Port $MgmtPort not reachable ($_)"
} finally {
    $tcp2.Close()
}

# ── Test 4: Container is running ────────────────────────────────────
Write-Host ""
Write-Host "[ 4 ] Cowrie container status"
$dockerStatus = ssh -i $IdentityFile -p $MgmtPort -o StrictHostKeyChecking=no `
    "${User}@${ip}" "docker ps --filter name=cowrie --format '{{.Status}}'" 2>$null

if ($dockerStatus -match "^Up") { Pass "Container is running ($dockerStatus)" }
else                             { Fail "Container not running (got: '$dockerStatus')" }

# ── Test 5: Log file exists and has entries ──────────────────────────
Write-Host ""
Write-Host "[ 5 ] Cowrie JSON log"
$logPath = "/root/cowrie-honeypot/volumes/var/log/cowrie/cowrie.json"
$logCheck = ssh -i $IdentityFile -p $MgmtPort -o StrictHostKeyChecking=no `
    "${User}@${ip}" "wc -l < $logPath 2>/dev/null || echo MISSING" 2>$null

if ($logCheck -eq "MISSING") {
    Fail "Log file not found at $logPath"
} else {
    Pass "Log file exists ($logCheck lines)"
    Info "Last 3 events:"
    ssh -i $IdentityFile -p $MgmtPort -o StrictHostKeyChecking=no `
        "${User}@${ip}" "tail -3 $logPath" 2>$null `
        | ForEach-Object { Info $_ }
}

# ── Summary ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "────────────────────────────────────"
Write-Host "  $pass passed, $fail failed"
Write-Host "────────────────────────────────────"
if ($fail -gt 0) { exit 1 }
