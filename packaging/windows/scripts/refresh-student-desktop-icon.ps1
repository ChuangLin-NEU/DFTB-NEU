# Rebuild desktop shortcut with a new icon filename to bust Windows icon cache.
$ErrorActionPreference = "Stop"
$install = Join-Path $env:LOCALAPPDATA "Programs\dftb-neu"
$srcIco = "C:\Users\13919\Projects\dftb-neu\packaging\windows\build\icon-student.ico"
if (-not (Test-Path $srcIco)) { throw "missing icon source" }
if (-not (Test-Path $install)) { throw "missing install dir" }

$stamp = Get-Date -Format "yyyyMMddHHmmss"
$iconName = "DFTB-workbench-$stamp.ico"
$iconPath = Join-Path $install $iconName
Copy-Item $srcIco $iconPath -Force
Copy-Item $srcIco (Join-Path $install "icon.ico") -Force
Copy-Item $srcIco (Join-Path $install "resources\icon.ico") -Force

Get-ChildItem $install -Filter "DFTB-workbench-*.ico" |
  Where-Object { $_.Name -ne $iconName } |
  Remove-Item -Force -ErrorAction SilentlyContinue

$exe = Get-ChildItem $install -Filter "*.exe" |
  Where-Object { $_.Name -notlike "Uninstall*" } |
  Select-Object -First 1
if (-not $exe) { throw "student exe not found" }

$wsh = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$iconLoc = $iconPath + ",0"

Get-ChildItem $desktop -Filter "*.lnk" | ForEach-Object {
  $s = $wsh.CreateShortcut($_.FullName)
  $t = [string]$s.TargetPath
  if ($t -match "dftb-neu\\" -and $t -notmatch "teacher") {
    Remove-Item $_.FullName -Force
    Write-Host ("removed " + $_.Name)
  }
}

# Name uses unicode escapes to keep script ASCII-safe for Windows PowerShell 5.1
$lnkName = ([string]([char]0x0044)) + "FTB" + [char]0x5DE5 + [char]0x4F5C + [char]0x53F0 + ".lnk"
$lnkPath = Join-Path $desktop $lnkName
$sc = $wsh.CreateShortcut($lnkPath)
$sc.TargetPath = $exe.FullName
$sc.WorkingDirectory = $install
$sc.WindowStyle = 1
$sc.Description = "DFTB Workbench"
$sc.IconLocation = $iconLoc
$sc.Save()
Write-Host ("created desktop shortcut -> " + $iconPath)

$smDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$smLnk = Join-Path $smDir $lnkName
$sc2 = $wsh.CreateShortcut($smLnk)
$sc2.TargetPath = $exe.FullName
$sc2.WorkingDirectory = $install
$sc2.WindowStyle = 1
$sc2.Description = "DFTB Workbench"
$sc2.IconLocation = $iconLoc
$sc2.Save()
Write-Host ("created start menu shortcut")

Get-Process explorer -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
Remove-Item (Join-Path $env:LOCALAPPDATA "IconCache.db") -Force -ErrorAction SilentlyContinue
$expCache = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Explorer"
Get-ChildItem $expCache -Filter "iconcache*" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem $expCache -Filter "thumbcache*" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
Start-Process explorer
Start-Sleep -Seconds 2
try { ie4uinit.exe -show } catch {}

$verify = $wsh.CreateShortcut($lnkPath)
Write-Host ("verify IconLocation=" + $verify.IconLocation)
Write-Host "done"
