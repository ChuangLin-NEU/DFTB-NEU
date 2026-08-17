$ErrorActionPreference = "Continue"

Get-NetTCPConnection -LocalPort 8791 -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'classroom_hub|uvicorn' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$tr = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\dftb-neu\scripts\start_classroom_hub_4060.ps1"'
schtasks /Delete /TN dftb-classroom-hub /F 2>$null | Out-Null
schtasks /Create /TN dftb-classroom-hub /TR $tr /SC ONLOGON /RL HIGHEST /F
if ($LASTEXITCODE -ne 0) {
  # fallback without HIGHEST
  schtasks /Create /TN dftb-classroom-hub /TR $tr /SC ONLOGON /RL LIMITED /F
}
schtasks /Run /TN dftb-classroom-hub
Write-Host "schtask_run_exit=$LASTEXITCODE"

Start-Sleep -Seconds 6
Write-Host "=== listen ==="
netstat -ano | findstr ":8791"
Write-Host "=== health ==="
try {
  $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
  Write-Host ("health=" + ($h | ConvertTo-Json -Compress))
} catch {
  Write-Host ("health_fail=" + $_.Exception.Message)
  Write-Host "---ERR---"
  Get-Content "D:\dftb-neu\data\classroom_hub.err.log" -Tail 40 -ErrorAction SilentlyContinue
  Write-Host "---OUT---"
  Get-Content "D:\dftb-neu\data\classroom_hub.out.log" -Tail 20 -ErrorAction SilentlyContinue
}
