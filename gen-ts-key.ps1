# Generates a new Tailscale auth key via the Tailscale API.
# Requires a Tailscale API key stored in ~/.tailscale-apikey
# (create one at tailscale.com → Settings → Keys → Generate API key)
#
# Use -Ephemeral for hosts that get regularly destroyed (e.g. cowrie).
# Ephemeral nodes are automatically removed from the tailnet when they go offline.
# Use non-ephemeral (default) for long-running hosts (e.g. log-stack).

param(
    [int]$ExpiryDays = 90,
    [switch]$Ephemeral
)

$apiKeyFile = Join-Path $env:USERPROFILE ".tailscale-apikey"

if (Test-Path $apiKeyFile) {
    $apiKey = (Get-Content $apiKeyFile -Raw).Trim()
} else {
    Write-Host "No API key found at $apiKeyFile"
    Write-Host "Generate one at: tailscale.com → Settings → Keys → Generate API key"
    Write-Host ""
    $apiKey = (Read-Host "Paste your Tailscale API key").Trim()
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        Write-Error "API key is required."
        exit 1
    }
    $save = Read-Host "Save to $apiKeyFile for future use? [y/N]"
    if ($save -ieq 'y') {
        $apiKey | Set-Content $apiKeyFile -NoNewline
        # Restrict to current user only
        $acl = Get-Acl $apiKeyFile
        $acl.SetAccessRuleProtection($true, $false)
        $acl.SetAccessRule(
            (New-Object System.Security.AccessControl.FileSystemAccessRule(
                [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
                "FullControl", "Allow"
            ))
        )
        Set-Acl $apiKeyFile $acl
        Write-Host "Saved."
    }
}

$body = @{
    capabilities = @{
        devices = @{
            create = @{
                reusable      = $false
                ephemeral     = [bool]$Ephemeral
                preauthorized = $false
                tags          = @()
            }
        }
    }
    expirySeconds = $ExpiryDays * 86400
} | ConvertTo-Json -Depth 10

try {
    $response = Invoke-RestMethod `
        -Uri "https://api.tailscale.com/api/v2/tailnet/-/keys" `
        -Method POST `
        -Headers @{ Authorization = "Bearer $apiKey" } `
        -ContentType "application/json" `
        -Body $body
} catch {
    $status = $_.Exception.Response.StatusCode.value__
    if ($status -eq 401) {
        Write-Error "API key rejected (401). Generate a new one at tailscale.com → Settings → Keys."
        if (Test-Path $apiKeyFile) {
            Remove-Item $apiKeyFile
            Write-Host "Removed stale key from $apiKeyFile"
        }
    } else {
        Write-Error "Tailscale API error ($status): $_"
    }
    exit 1
}

$expires = [datetime]$response.expires
$ephemeralLabel = if ($Ephemeral) { " ephemeral," } else { "" }
Write-Host ""
Write-Host "Tailscale auth key ($ephemeralLabel expires $($expires.ToString('yyyy-MM-dd'))):"
Write-Host ""
Write-Host "  $($response.key)"
Write-Host ""
if ($Ephemeral) {
    Write-Host "This node will be automatically removed from the tailnet when it goes offline."
} else {
    Write-Host "Use this as TS_AUTHKEY when running setup.sh on a new host."
}
