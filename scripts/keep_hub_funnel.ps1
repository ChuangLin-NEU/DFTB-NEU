# Keep Tailscale Funnel public classroom hub alive (stable HTTPS, no localhost.run).
# Prefer running on 4060 (hub host). Can also run from laptop via SSH to 4060.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$UrlFile = Join-Path $Root "data\classroom\public_hub_url.txt"
$LogFile = Join-Path $env:TEMP "dftb-hub-funnel-keep.log"
$FunnelUrl = if ($env:DFTB_FUNNEL_HUB_URL) { $env:DFTB_FUNNEL_HUB_URL.TrimEnd("/") } else { "https://desktop-ibhgp7g.tailcc9705.ts.net" }
$HubPort = if ($env:DFTB_CLASS_PORT) { [int]$env:DFTB_CLASS_PORT } else { 8791 }
$RemoteHost = if ($env:DFTB_FUNNEL_SSH_HOST) { $env:DFTB_FUNNEL_SSH_HOST } else { "4060" }
$IntervalSec = if ($env:DFTB_FUNNEL_KEEP_INTERVAL) { [int]$env:DFTB_FUNNEL_KEEP_INTERVAL } else { 45 }

function Write-Log([string]$msg) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
  Add-Content -Path $LogFile -Value $line -Encoding utf8
}

function Test-Url([string]$url) {
  if (-not $url) { return $false }
  try {
    # Prefer Python/certifi path when available; fall back to Invoke-WebRequest.
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $py) {
      $code = @"
import httpx, certifi, sys
u=sys.argv[1]
try:
  r=httpx.get(u+'/health', timeout=20, verify=certifi.where(), trust_env=False)
  sys.exit(0 if r.status_code==200 else 1)
except Exception:
  sys.exit(1)
"@
      & $py -c $code $url | Out-Null
      return ($LASTEXITCODE -eq 0)
    }
    $r = Invoke-WebRequest "$url/health" -UseBasicParsing -TimeoutSec 15
    return ($r.StatusCode -eq 200)
  } catch {
    return $false
  }
}

function Test-LocalHub {
  try {
    $r = Invoke-WebRequest "http://127.0.0.1:$HubPort/health" -UseBasicParsing -TimeoutSec 3
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

function Ensure-LocalFunnel {
  if (-not (Test-LocalHub)) {
    Write-Log "local hub down on :$HubPort"
    return $false
  }
  $status = & tailscale funnel status 2>&1 | Out-String
  if ($status -match [regex]::Escape(($FunnelUrl -replace '^https://','')) -and $status -match "Funnel on") {
    return $true
  }
  & tailscale funnel --bg --yes "http://127.0.0.1:$HubPort" 2>&1 | Out-Null
  Start-Sleep -Seconds 2
  return $true
}

function Ensure-RemoteFunnel {
  $cmd = @"
`$ErrorActionPreference='Continue'
try { Invoke-WebRequest http://127.0.0.1:$HubPort/health -UseBasicParsing -TimeoutSec 3 | Out-Null } catch { exit 2 }
`$st = tailscale funnel status 2>&1 | Out-String
if (`$st -notmatch 'Funnel on' -or `$st -notmatch '8791') {
  tailscale funnel --bg --yes http://127.0.0.1:$HubPort | Out-Null
}
exit 0
"@
  $b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
  ssh -o BatchMode=yes -o ConnectTimeout=12 $RemoteHost "powershell -NoProfile -EncodedCommand $b64" 2>&1 | Out-Null
  return ($LASTEXITCODE -eq 0)
}

New-Item -ItemType Directory -Force -Path (Split-Path $UrlFile) | Out-Null
Set-Content -Path $UrlFile -Value $FunnelUrl -Encoding utf8
Write-Log "keep-funnel start url=$FunnelUrl"

$isHubHost = Test-LocalHub
while ($true) {
  try {
    if (Test-Url $FunnelUrl) {
      Write-Log "ok $FunnelUrl"
    } else {
      Write-Log "down; repairing"
      if ($isHubHost -or (Test-LocalHub)) {
        [void](Ensure-LocalFunnel)
      } else {
        [void](Ensure-RemoteFunnel)
      }
      Start-Sleep -Seconds 5
      if (Test-Url $FunnelUrl) { Write-Log "repaired" } else { Write-Log "still down" }
    }
  } catch {
    Write-Log ("err " + $_.Exception.Message)
  }
  Start-Sleep -Seconds $IntervalSec
}
