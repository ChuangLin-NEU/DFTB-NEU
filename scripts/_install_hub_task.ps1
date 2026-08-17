# Install/run a Scheduled Task so hub survives SSH disconnect (Windows OpenSSH job kill)
$ErrorActionPreference = "Stop"

# Ensure provider=deepseek in env file
$envPath = "D:\cmats-lab\.env"
if (Test-Path $envPath) {
  $raw = Get-Content $envPath -Raw
  if ($raw -match "(?m)^CMATS_LLM_PROVIDER=.*$") {
    $raw = [regex]::Replace($raw, "(?m)^CMATS_LLM_PROVIDER=.*$", "CMATS_LLM_PROVIDER=deepseek")
  } else {
    $raw = $raw.TrimEnd() + "`r`nCMATS_LLM_PROVIDER=deepseek`r`n"
  }
  [System.IO.File]::WriteAllText($envPath, $raw)
}

$launcher = "D:\dftb-neu\scripts\start_classroom_hub_4060.ps1"
# Patch start script to force deepseek after loading env
$startTxt = Get-Content $launcher -Raw
if ($startTxt -notmatch "FORCE DEEPSEEK PROVIDER") {
  $startTxt = $startTxt -replace \
    'if \(-not \$env:DFTB_CLASS_LLM_PROVIDER\) \{ \$env:DFTB_CLASS_LLM_PROVIDER = "deepseek" \}', `
    "if (-not `$env:DFTB_CLASS_LLM_PROVIDER) { `$env:DFTB_CLASS_LLM_PROVIDER = `"deepseek`" }`r`n# FORCE DEEPSEEK PROVIDER`r`n`$env:DFTB_CLASS_LLM_PROVIDER = `"deepseek`""
  [System.IO.File]::WriteAllText($launcher, $startTxt)
}

$taskName = "DFTB-ClassroomHub"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`"" `
  -WorkingDirectory "D:\dftb-neu"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero)
# SYSTEM so the hub survives SSH disconnect / user session quirks
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "registered task $taskName"

# Kill any zombie then run task
Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 6

$h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
Write-Host ("local provider=" + $h.llm_provider + " ds=" + $h.deepseek_key_set)

& tailscale funnel --https=443 off 2>$null | Out-Null
Start-Sleep -Seconds 1
& tailscale funnel --bg --yes "http://127.0.0.1:8791" | Out-Null
Start-Sleep -Seconds 2
$h2 = Invoke-RestMethod "https://desktop-ibhgp7g.tailcc9705.ts.net/health" -TimeoutSec 20
Write-Host ("public provider=" + $h2.llm_provider)

# Funnel keeper task (optional lightweight)
$funnelLauncher = "D:\dftb-neu\scripts\keep_hub_funnel.ps1"
if (Test-Path $funnelLauncher) {
  $ft = "DFTB-HubFunnelKeep"
  $faction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$funnelLauncher`"" `
    -WorkingDirectory "D:\dftb-neu"
  # every 5 minutes
  $ftrig = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ([TimeSpan]::MaxValue)
  Unregister-ScheduledTask -TaskName $ft -Confirm:$false -ErrorAction SilentlyContinue
  Register-ScheduledTask -TaskName $ft -Action $faction -Trigger $ftrig -Settings $settings -Principal $principal -Force | Out-Null
  Write-Host "registered funnel keeper $ft"
}

Write-Host "DONE"
