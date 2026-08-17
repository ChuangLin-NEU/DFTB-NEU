Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue |
  Format-Table OwningProcess, State -AutoSize
Write-Host "--- err ---"
Get-Content "D:\dftb-neu\data\classroom_hub.err.log" -Tail 40 -ErrorAction SilentlyContinue
Write-Host "--- out ---"
Get-Content "D:\dftb-neu\data\classroom_hub.out.log" -Tail 20 -ErrorAction SilentlyContinue
try {
  $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
  Write-Host ("health ok deepseek=" + $h.deepseek_key_set)
} catch {
  Write-Host ("health fail: " + $_.Exception.Message)
}
