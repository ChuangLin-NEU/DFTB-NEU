$ErrorActionPreference = "Continue"
$url = "https://desktop-ibhgp7g.tailcc9705.ts.net/health"
for ($i = 1; $i -le 5; $i++) {
  try {
    $h = Invoke-RestMethod $url -TimeoutSec 20
    Write-Host ("try" + $i + " OK provider=" + $h.llm_provider + " ds=" + $h.deepseek_key_set)
    exit 0
  } catch {
    Write-Host ("try" + $i + " FAIL " + $_.Exception.Message)
    Start-Sleep -Seconds 2
  }
}
Write-Host "=== funnel status ==="
& tailscale funnel status
Write-Host "=== listeners 8791 ==="
Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue |
  Format-Table OwningProcess,LocalAddress,LocalPort -AutoSize
try {
  $h2 = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
  Write-Host ("local OK provider=" + $h2.llm_provider)
} catch {
  Write-Host ("local FAIL " + $_.Exception.Message)
}
