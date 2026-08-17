$ErrorActionPreference = "Continue"
Write-Host "=== err log tail ==="
if (Test-Path "D:\dftb-neu\data\classroom_hub.err.log") {
  Get-Content "D:\dftb-neu\data\classroom_hub.err.log" -Tail 40
}
Write-Host "=== out log tail ==="
if (Test-Path "D:\dftb-neu\data\classroom_hub.out.log") {
  Get-Content "D:\dftb-neu\data\classroom_hub.out.log" -Tail 20
}

Write-Host "=== start hub ==="
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\dftb-neu\scripts\start_classroom_hub_4060.ps1"
Start-Sleep -Seconds 5
Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue |
  Format-Table OwningProcess,State -AutoSize
try {
  $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
  Write-Host ("local health provider=" + $h.llm_provider + " ds=" + $h.deepseek_key_set)
} catch {
  Write-Host ("local health FAIL: " + $_.Exception.Message)
  Write-Host "=== err after start ==="
  Get-Content "D:\dftb-neu\data\classroom_hub.err.log" -Tail 50 -ErrorAction SilentlyContinue
}

Write-Host "=== reset funnel ==="
& tailscale funnel --https=443 off 2>$null
Start-Sleep -Seconds 1
& tailscale funnel --bg --yes "http://127.0.0.1:8791"
Start-Sleep -Seconds 3
try {
  $h2 = Invoke-RestMethod "https://desktop-ibhgp7g.tailcc9705.ts.net/health" -TimeoutSec 20
  Write-Host ("public health provider=" + $h2.llm_provider)
} catch {
  Write-Host ("public health FAIL: " + $_.Exception.Message)
}
