$ErrorActionPreference = "Continue"
$src = "C:\Users\13919\Projects\dftb-neu"
$stu = "C:\Users\13919\AppData\Local\Programs\dftb-neu\resources"
$tea = "C:\Users\13919\AppData\Local\Programs\dftb-neu-teacher\resources"

function Sync-Dir($from, $to) {
  if (-not (Test-Path $from)) { Write-Host "missing $from"; return }
  if (Test-Path $to) { Remove-Item -Recurse -Force $to }
  $parent = Split-Path $to
  if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
  Copy-Item -Recurse -Force $from $to
  Write-Host "synced $from -> $to"
}

Get-ChildItem $src -Recurse -Force -Filter "._*" -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue

Sync-Dir "$src\apps\web" "$stu\web"
Sync-Dir "$src\apps\api" "$stu\api"
Sync-Dir "$src\engines" "$stu\engines"
Sync-Dir "$src\templates" "$stu\templates"
Sync-Dir "$src\scripts" "$stu\scripts"
Sync-Dir "$src\apps\teacher_web" "$tea\teacher_web"

$helper = @'
param()
$src = "C:\Users\13919\Projects\dftb-neu"
$stu = "C:\Users\13919\AppData\Local\Programs\dftb-neu\resources"
$tea = "C:\Users\13919\AppData\Local\Programs\dftb-neu-teacher\resources"
function Sync-Dir($from, $to) {
  if (Test-Path $to) { Remove-Item -Recurse -Force $to }
  Copy-Item -Recurse -Force $from $to
  Write-Host "OK $from"
}
Sync-Dir "$src\apps\web" "$stu\web"
Sync-Dir "$src\apps\api" "$stu\api"
Sync-Dir "$src\engines" "$stu\engines"
Sync-Dir "$src\templates" "$stu\templates"
Sync-Dir "$src\scripts" "$stu\scripts"
Sync-Dir "$src\apps\teacher_web" "$tea\teacher_web"
Write-Host "DONE - restart DFTB apps"
'@
Set-Content -Path "$src\sync-to-installed.ps1" -Value $helper -Encoding UTF8

# Update desktop shortcuts to 0.2.1 installs
$WshShell = New-Object -ComObject WScript.Shell
$desk = [Environment]::GetFolderPath("Desktop")
$stuExe = "C:\Users\13919\AppData\Local\Programs\dftb-neu\DFTB工作台.exe"
$teaExe = "C:\Users\13919\AppData\Local\Programs\dftb-neu-teacher\DFTB教师端.exe"
# resolve actual exe names
$stuExe = (Get-ChildItem "C:\Users\13919\AppData\Local\Programs\dftb-neu\*.exe" | Where-Object { $_.Name -notlike "Uninstall*" } | Select-Object -First 1).FullName
$teaExe = (Get-ChildItem "C:\Users\13919\AppData\Local\Programs\dftb-neu-teacher\*.exe" | Where-Object { $_.Name -notlike "Uninstall*" } | Select-Object -First 1).FullName
Write-Host "stuExe=$stuExe"
Write-Host "teaExe=$teaExe"
if ($stuExe) {
  $s = $WshShell.CreateShortcut("$desk\DFTB工作台.lnk")
  $s.TargetPath = $stuExe
  $s.WorkingDirectory = Split-Path $stuExe
  $s.Save()
}
if ($teaExe) {
  $s = $WshShell.CreateShortcut("$desk\DFTB教师端.lnk")
  $s.TargetPath = $teaExe
  $s.WorkingDirectory = Split-Path $teaExe
  $s.Save()
}

Write-Host "=== verify ==="
Write-Host ("web=" + (Test-Path "$stu\web\index.html"))
Write-Host ("api=" + (Test-Path "$stu\api\dftbneu\main.py"))
Write-Host ("teacher=" + (Test-Path "$tea\teacher_web\index.html"))
if (Test-Path "$tea\teacher_web\config.json") { Get-Content "$tea\teacher_web\config.json" -Raw }
Write-Host DONE
