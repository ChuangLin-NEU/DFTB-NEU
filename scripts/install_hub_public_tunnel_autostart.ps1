# 注册“登录时自动启动”课堂公网隧道守护
# powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_hub_public_tunnel_autostart.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Keep = Join-Path $Root "scripts\keep_hub_public_tunnel.ps1"
$Start = Join-Path $Root "scripts\start_hub_public_tunnel.ps1"
if (-not (Test-Path $Keep)) { throw "missing $Keep" }

$TaskName = "DFTB-Classroom-Hub-Public-Tunnel"
$arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Keep`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

# 立刻先起一次隧道 + 守护（避免等到下次登录）
Start-Process powershell.exe -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File",$Start -WindowStyle Hidden | Out-Null
Start-Sleep -Seconds 2
# 若守护未在跑则启动
$alive = Get-CimInstance Win32_Process -EA SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "keep_hub_public_tunnel\.ps1" }
if (-not $alive) {
  Start-Process powershell.exe -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-WindowStyle","Hidden","-File",$Keep -WorkingDirectory $Root | Out-Null
}

Write-Output "scheduled_task=$TaskName"
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State
Write-Output "keep_script=$Keep"
