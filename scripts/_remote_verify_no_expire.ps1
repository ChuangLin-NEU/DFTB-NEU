$ErrorActionPreference = "Continue"
$p = "D:\dftb-neu\apps\classroom_hub\main.py"
Write-Host "exists=$(Test-Path $p)"
$hit1 = Select-String -Path $p -Pattern "session_days: int = Field\(0" -Quiet
$hit2 = Select-String -Path $p -Pattern "100 \* 365 \* 86400" -Quiet
Write-Host "field0=$hit1 far_expire=$hit2"
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\dftb-neu\scripts\_remote_hub_relaunch.ps1"
Start-Sleep -Seconds 4
try {
  $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 8
  Write-Host ("health_ok=" + $h.ok + "; service=" + $h.service)
} catch {
  Write-Host ("health_fail=" + $_.Exception.Message)
  Get-Content "D:\dftb-neu\data\classroom_hub.err.log" -Tail 30 -ErrorAction SilentlyContinue
}
