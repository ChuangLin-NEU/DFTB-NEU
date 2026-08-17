# One-shot: ensure classroom hub Funnel is up and write the fixed public URL.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$UrlFile = Join-Path $Root "data\classroom\public_hub_url.txt"
$FunnelUrl = if ($env:DFTB_FUNNEL_HUB_URL) { $env:DFTB_FUNNEL_HUB_URL.TrimEnd("/") } else { "https://desktop-ibhgp7g.tailcc9705.ts.net" }
$HubPort = if ($env:DFTB_CLASS_PORT) { [int]$env:DFTB_CLASS_PORT } else { 8791 }
$RemoteHost = if ($env:DFTB_FUNNEL_SSH_HOST) { $env:DFTB_FUNNEL_SSH_HOST } else { "4060" }

New-Item -ItemType Directory -Force -Path (Split-Path $UrlFile) | Out-Null
Set-Content -Path $UrlFile -Value $FunnelUrl -Encoding utf8

function Test-LocalHub {
  try {
    $r = Invoke-WebRequest "http://127.0.0.1:$HubPort/health" -UseBasicParsing -TimeoutSec 3
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

if (Test-LocalHub) {
  & tailscale funnel --bg --yes "http://127.0.0.1:$HubPort"
} else {
  $cmd = "tailscale funnel --bg --yes http://127.0.0.1:$HubPort"
  ssh -o BatchMode=yes -o ConnectTimeout=15 $RemoteHost $cmd
}

Write-Output "PUBLIC_HUB_URL=$FunnelUrl"
Write-Output "url_file=$UrlFile"

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $py) {
  & $py -c @"
import httpx, certifi, sys
u=sys.argv[1]
r=httpx.get(u+'/health', timeout=25, verify=certifi.where(), trust_env=False)
print('health', r.status_code, r.text[:120])
sys.exit(0 if r.status_code==200 else 1)
"@ $FunnelUrl
} else {
  $h = Invoke-RestMethod "$FunnelUrl/health" -TimeoutSec 20
  Write-Output ("health_ok=" + $h.ok)
}
