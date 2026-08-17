Write-Host "=== process ==="
Get-Process | Where-Object { $_.Id -eq 17008 -or $_.ProcessName -match 'python|uvicorn' } |
  Select-Object Id, ProcessName, Path | Format-Table -AutoSize
Write-Host "=== port 8791 ==="
Get-NetTCPConnection -LocalPort 8791 -ErrorAction SilentlyContinue |
  Format-Table LocalAddress, State, OwningProcess -AutoSize
Write-Host "=== err log ==="
if (Test-Path 'D:\dftb-neu\data\classroom_hub.err.log') {
  Get-Content 'D:\dftb-neu\data\classroom_hub.err.log' -Tail 50
} else { 'no err log' }
Write-Host "=== out log ==="
if (Test-Path 'D:\dftb-neu\data\classroom_hub.out.log') {
  Get-Content 'D:\dftb-neu\data\classroom_hub.out.log' -Tail 30
} else { 'no out log' }
Write-Host "=== local health ==="
try { Invoke-RestMethod 'http://127.0.0.1:8791/health' -TimeoutSec 3 | ConvertTo-Json -Compress }
catch { $_.Exception.Message }
