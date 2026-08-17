$ErrorActionPreference = "Continue"
Write-Host "=== listen 8791 ==="
Get-NetTCPConnection -LocalPort 8791 -ErrorAction SilentlyContinue |
  Format-Table OwningProcess,State,LocalAddress,RemoteAddress -AutoSize
Write-Host "=== process ==="
Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue |
    Format-Table Id,ProcessName,Path -AutoSize
}
Write-Host "=== curl local ==="
try {
  $r = Invoke-WebRequest "http://127.0.0.1:8791/health" -UseBasicParsing -TimeoutSec 5
  Write-Host ("local status=" + $r.StatusCode + " body=" + $r.Content)
} catch {
  Write-Host ("local FAIL " + $_.Exception.Message)
}
Write-Host "=== curl tailnet ip ==="
try {
  $r2 = Invoke-WebRequest "http://100.127.118.69:8791/health" -UseBasicParsing -TimeoutSec 5
  Write-Host ("tailnet status=" + $r2.StatusCode + " body=" + $r2.Content)
} catch {
  Write-Host ("tailnet FAIL " + $_.Exception.Message)
}
Write-Host "=== tailscale serve/funnel ==="
& tailscale serve status 2>&1 | Out-String | Write-Host
& tailscale funnel status 2>&1 | Out-String | Write-Host
Write-Host "=== err log ==="
Get-Content "D:\dftb-neu\data\classroom_hub.err.log" -Tail 30 -ErrorAction SilentlyContinue
