# Opens a raw TCP connection to port 3306 and reads the MySQL server greeting.
# A valid greeting confirms the honeypot is running and speaking MySQL protocol.

param([int]$Port = 3306)

$cache = Join-Path $PSScriptRoot ".server-ip"
if (Test-Path $cache) {
    $ip = (Get-Content $cache).Trim()
} else {
    $ip = (Read-Host "Server IP address").Trim()
}

Write-Host "Connecting to ${ip}:${Port}..."
$tcp = New-Object System.Net.Sockets.TcpClient
try {
    $tcp.Connect($ip, $Port)
    if ($tcp.Connected) {
        $stream = $tcp.GetStream()
        $stream.ReadTimeout = 3000
        $buf = New-Object byte[] 512
        $read = $stream.Read($buf, 0, $buf.Length)
        if ($read -gt 5) {
            # Skip 4-byte packet header; version string starts at byte 5 (0x0a protocol marker + version)
            $versionBytes = $buf[5..([Math]::Min($read - 1, 30))]
            $version = [System.Text.Encoding]::ASCII.GetString($versionBytes).Split([char]0)[0]
            Write-Host "OK — server greeted with MySQL $version"
        } else {
            Write-Host "Connected but received unexpected response (${read} bytes)."
        }
    }
} catch {
    Write-Warning "Connection failed: $_"
} finally {
    $tcp.Close()
}
