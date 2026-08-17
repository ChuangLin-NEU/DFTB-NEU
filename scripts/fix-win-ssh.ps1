# DFTB: one-shot OpenSSH fix for Windows laptop (admin PowerShell)
$ErrorActionPreference = "Continue"
Write-Host "=== DFTB OpenSSH fix ==="

# 1) Locate or reinstall OpenSSH
$sshd = Get-Command sshd.exe -ErrorAction SilentlyContinue
$dirs = @(
  "C:\Program Files\OpenSSH",
  "C:\Program Files\OpenSSH-Win64",
  "C:\Program Files\OpenSSH\OpenSSH-Win64",
  "$env:ProgramFiles\OpenSSH",
  "$env:ProgramFiles\OpenSSH-Win64"
)
$oshDir = $dirs | Where-Object { Test-Path (Join-Path $_ "sshd.exe") } | Select-Object -First 1

if (-not $oshDir) {
  Write-Host "OpenSSH binaries missing; reinstalling Preview via winget..."
  winget install --id Microsoft.OpenSSH.Preview -e --accept-source-agreements --accept-package-agreements --disable-interactivity
  Start-Sleep -Seconds 2
  $oshDir = $dirs | Where-Object { Test-Path (Join-Path $_ "sshd.exe") } | Select-Object -First 1
}

if (-not $oshDir) {
  # fallback: download zip
  Write-Host "winget path failed; downloading OpenSSH zip..."
  $zip = "$env:TEMP\OpenSSH-Win64.zip"
  $url = "https://github.com/PowerShell/Win32-OpenSSH/releases/download/v9.8.3.0p2-Preview/OpenSSH-Win64.zip"
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $url -OutFile $zip
  $dest = "C:\Program Files\OpenSSH-Win64"
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  Expand-Archive -Path $zip -DestinationPath $dest -Force
  if (Test-Path "$dest\OpenSSH-Win64\sshd.exe") { $oshDir = "$dest\OpenSSH-Win64" }
  elseif (Test-Path "$dest\sshd.exe") { $oshDir = $dest }
}

if (-not $oshDir -or -not (Test-Path "$oshDir\sshd.exe")) {
  Write-Host "FATAL: sshd.exe not found"
  exit 1
}
Write-Host "OpenSSH dir: $oshDir"

# 2) Register service if missing
$svc = Get-Service -Name sshd -ErrorAction SilentlyContinue
if (-not $svc) {
  $svc = Get-Service | Where-Object { $_.Name -match 'ssh' -or $_.DisplayName -match 'OpenSSH.*Server' } | Select-Object -First 1
}
if (-not $svc) {
  Write-Host "Registering sshd service..."
  if (Test-Path "$oshDir\install-sshd.ps1") {
    & "$oshDir\install-sshd.ps1"
  } else {
    & "$oshDir\sshd.exe" install-sshd 2>$null
    if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
      New-Service -Name sshd -BinaryPathName "`"$oshDir\sshd.exe`"" -DisplayName "OpenSSH SSH Server" -StartupType Automatic | Out-Null
    }
  }
}

# Ensure PATH contains OpenSSH for this session
$env:Path = "$oshDir;" + $env:Path

# 3) Firewall
try {
  New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -DisplayName "OpenSSH Server (sshd)" -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -ErrorAction Stop | Out-Null
} catch {
  # already exists is fine
}

# 4) Admin authorized_keys (required for Administrators group users)
New-Item -ItemType Directory -Force -Path "$env:ProgramData\ssh" | Out-Null
$pub = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQD7t4UAsUTY7f2nZ1FBJGeuqqU9KWl3BUQ85H3kthc/ouBxiuVEX81WnmiISz90Fm0arCKvcWz4l/coAgCBz4RibF50kOSnjcvn4B2aJy6w/BlFqZ/lwzqfEDLsdMKV7IhmQpDGZ1/PgLe1OQd0AgjcN3YH5tUFRtdb+Kp5W2kb4CrJWFxDfCAeDIjPzw6JAt0NpP5OQR96AIaDhbrth0iEV9sjv+r7BWb/ZXhmNNivYJGL3/mvtq8ty29ZyCN9AJ8GVubP/kyUnNLXGgmk1/By3/gvnVaViV76tnuJUxhGcw7BNOc6W0VKeU6jbuvK4GtuUvRl7lB4ROdCkLZ+o4WhC68jQsYOM+vJYWm5+zaZNwdyXfaKnqFy4jDumtFWsTBbR830suoN3w+H/eeU/xD5WZSx3ZNN6FQOeblHsBxtnugp9C9PJoyk28IxiyFyqZrrKav5GKc275EnafPRv1v5r5BZdVUgL69LJ+hnhYUSQEU6fNAtAGraczKJV2DQigPXxfkOZJgR8vZ5kZkntVxwwLGbjzXoiz5aSumm90KOx3Jbc8ofIC9Wh9x/g/fHgF8eo9UdIx7fU1qr2Z/wyNbXSLlkgjGeeWV2zlIe8YIAxE+dAJaiiN94ppqza64B80YiFir9QEnpDTryho4TCUq90qXxQzsFTI2gC/UEIoSIwQ== mu@mudeMac-mini.local"
$akAdmin = "$env:ProgramData\ssh\administrators_authorized_keys"
Set-Content -Path $akAdmin -Value $pub -Encoding ascii
cmd /c "icacls `"$akAdmin`" /inheritance:r" | Out-Null
cmd /c "icacls `"$akAdmin`" /grant SYSTEM:(F)" | Out-Null
cmd /c "icacls `"$akAdmin`" /grant *S-1-5-32-544:(F)" | Out-Null

# Also user key (non-admin path)
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh" | Out-Null
$akUser = "$env:USERPROFILE\.ssh\authorized_keys"
Set-Content -Path $akUser -Value $pub -Encoding ascii
cmd /c "icacls `"$env:USERPROFILE\.ssh`" /inheritance:r" | Out-Null
cmd /c "icacls `"$env:USERPROFILE\.ssh`" /grant `"$env:USERNAME`:(F)`"" | Out-Null
cmd /c "icacls `"$akUser`" /inheritance:r" | Out-Null
cmd /c "icacls `"$akUser`" /grant `"$env:USERNAME`:(R)`"" | Out-Null

# 5) sshd_config essentials
$cfgCandidates = @(
  "$env:ProgramData\ssh\sshd_config",
  "$oshDir\sshd_config_default",
  "$oshDir\sshd_config"
)
$cfg = "$env:ProgramData\ssh\sshd_config"
if (-not (Test-Path $cfg)) {
  $src = $cfgCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($src -and $src -ne $cfg) { Copy-Item $src $cfg -Force }
}
if (Test-Path $cfg) {
  $txt = Get-Content $cfg -Raw
  if ($txt -notmatch "(?m)^PubkeyAuthentication\s+yes") {
    Add-Content $cfg "`nPubkeyAuthentication yes`nPasswordAuthentication yes`n"
  }
}

# 6) Start service
$svcName = "sshd"
if (-not (Get-Service -Name sshd -ErrorAction SilentlyContinue)) {
  $alt = Get-Service | Where-Object { $_.DisplayName -match 'OpenSSH.*Server' } | Select-Object -First 1
  if ($alt) { $svcName = $alt.Name }
}
Write-Host "Service name: $svcName"
try { Set-Service -Name $svcName -StartupType Automatic } catch {}
try { Start-Service -Name $svcName -ErrorAction Stop } catch {
  Write-Host "Start-Service failed: $($_.Exception.Message)"
  # last resort: run sshd in background once
  Start-Process -FilePath "$oshDir\sshd.exe" -ArgumentList "-D" -WindowStyle Hidden
}
Start-Sleep -Seconds 2

Write-Host "--- status ---"
Get-Service -Name $svcName -ErrorAction SilentlyContinue | Format-List Name,Status,StartType
Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort
Write-Host "USER=$env:USERNAME"
Write-Host "WHOAMI=$(whoami)"
Write-Host "=== DONE: tell agent OK ==="
