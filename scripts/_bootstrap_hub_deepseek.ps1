$ErrorActionPreference = "Stop"

# 1) force deepseek in .env
$envPath = "D:\cmats-lab\.env"
$raw = Get-Content $envPath -Raw
$raw = [regex]::Replace($raw, "(?m)^CMATS_LLM_PROVIDER=.*$", "CMATS_LLM_PROVIDER=deepseek")
[System.IO.File]::WriteAllText($envPath, $raw)

# 2) ensure start script forces provider at end
$launcher = "D:\dftb-neu\scripts\start_classroom_hub_4060.ps1"
$lt = Get-Content $launcher -Raw
if ($lt -notmatch "FORCE DEEPSEEK PROVIDER") {
  $lt = $lt.TrimEnd() + "`r`n`r`n# FORCE DEEPSEEK PROVIDER`r`n`$env:DFTB_CLASS_LLM_PROVIDER = `"deepseek`"`r`n"
  [System.IO.File]::WriteAllText($launcher, $lt)
}

# 3) scheduled task under SYSTEM
$taskName = "DFTB-ClassroomHub"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`"" `
  -WorkingDirectory "D:\dftb-neu"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $taskName

$ok = $false
for ($i=1; $i -le 15; $i++) {
  Start-Sleep -Seconds 1
  try {
    $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 3
    Write-Host ("ready provider=" + $h.llm_provider + " ds=" + $h.deepseek_key_set)
    $ok = $true
    break
  } catch {}
}
if (-not $ok) { throw "hub not ready" }

& tailscale funnel --https=443 off 2>$null | Out-Null
Start-Sleep -Seconds 1
& tailscale funnel --bg --yes "http://127.0.0.1:8791" | Out-Null
Start-Sleep -Seconds 3
$h2 = Invoke-RestMethod "https://desktop-ibhgp7g.tailcc9705.ts.net/health" -TimeoutSec 20
Write-Host ("public provider=" + $h2.llm_provider)

# wait to ensure not dying immediately
Start-Sleep -Seconds 8
$h3 = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 3
Write-Host ("still_alive provider=" + $h3.llm_provider)
Write-Host "BOOTSTRAP_OK"
