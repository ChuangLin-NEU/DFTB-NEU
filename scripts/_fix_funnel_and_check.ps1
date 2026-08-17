$ErrorActionPreference = "Continue"
Write-Host "=== local hub ==="
try {
  $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
  Write-Host ("provider=" + $h.llm_provider + " ds=" + $h.deepseek_key_set + " qw=" + $h.qwen_key_set)
} catch {
  Write-Host ("local health FAIL: " + $_.Exception.Message)
  powershell -NoProfile -ExecutionPolicy Bypass -File "D:\dftb-neu\scripts\start_classroom_hub_4060.ps1"
  Start-Sleep -Seconds 3
  $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
  Write-Host ("provider=" + $h.llm_provider)
}

Write-Host "=== funnel ==="
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\dftb-neu\scripts\start_hub_funnel.ps1"
Start-Sleep -Seconds 2
try {
  $status = & tailscale funnel status 2>&1 | Out-String
  Write-Host $status
} catch {
  Write-Host ("funnel status err: " + $_.Exception.Message)
}
