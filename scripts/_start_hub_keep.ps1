# Robust hub start on 4060: keep process alive, set provider=deepseek, restore funnel
$ErrorActionPreference = "Continue"

# Ensure provider
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

# Kill old listeners
Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "classroom_hub|uvicorn" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$env:DFTB_CLASS_HOST = "0.0.0.0"
$env:DFTB_CLASS_PORT = "8791"
$env:DFTB_CLASS_DATA = "D:\dftb-neu\data\classroom"
$env:DFTB_CLASS_TEACHER_PASSWORD = "zl303@"
$env:DFTB_CLASS_ADMIN_SECRET = "zl303@"
$env:DFTB_CLASS_TOKEN_SECRET = "zl303@"
$env:PYTHONPATH = "D:\dftb-neu\apps"
$env:DFTB_CLASS_LLM_PROVIDER = "deepseek"

function Import-HubEnvFile([string]$path) {
  if (-not (Test-Path $path)) { return }
  Get-Content $path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    if ($line -match "^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
      Set-Item -Path ("Env:" + $Matches[1]) -Value ($Matches[2].Trim().Trim('"').Trim("'"))
    }
  }
}
Import-HubEnvFile "D:\dftb-neu\data\classroom\secrets.env"
if (Test-Path $envPath) {
  Get-Content $envPath | ForEach-Object {
    if ($_ -match "^CMATS_DEEPSEEK_API_KEY=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_API_KEY=(.*)$") { $env:DFTB_CLASS_LLM_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_MP_API_KEY=(.*)$") { $env:DFTB_CLASS_MP_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_PROVIDER=(.*)$") { $env:DFTB_CLASS_LLM_PROVIDER = $Matches[1].Trim() }
    if ($_ -match "^CMATS_DEEPSEEK_BASE_URL=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_BASE_URL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_DEEPSEEK_MODEL=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_MODEL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_BASE_URL=(.*)$") { $env:DFTB_CLASS_LLM_BASE_URL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_MODEL=(.*)$") { $env:DFTB_CLASS_LLM_MODEL = $Matches[1].Trim() }
  }
}
# Force deepseek regardless of file order
$env:DFTB_CLASS_LLM_PROVIDER = "deepseek"

$py = "D:\cmats-lab\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$outLog = "D:\dftb-neu\data\classroom_hub.out.log"
$errLog = "D:\dftb-neu\data\classroom_hub.err.log"
"" | Set-Content $outLog
"" | Set-Content $errLog

# Use cmd start to detach from SSH session lifetime
$arg = "-NoProfile -ExecutionPolicy Bypass -Command `"& '$py' -m uvicorn classroom_hub.main:app --app-dir 'D:\dftb-neu\apps' --host 0.0.0.0 --port 8791 *> '$errLog'`""
$p = Start-Process -FilePath "powershell.exe" -ArgumentList $arg -WorkingDirectory "D:\dftb-neu" `
  -WindowStyle Hidden -PassThru
"wrapper_pid=$($p.Id)" | Set-Content "D:\dftb-neu\data\classroom_hub.pid.txt"

$ok = $false
for ($i = 1; $i -le 10; $i++) {
  Start-Sleep -Seconds 1
  try {
    $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 3
    Write-Host ("ready provider=" + $h.llm_provider + " ds=" + $h.deepseek_key_set + " qw=" + $h.qwen_key_set)
    $ok = $true
    break
  } catch {}
}
if (-not $ok) {
  Write-Host "hub failed to become ready"
  Get-Content $errLog -Tail 40
  exit 1
}

# Funnel
& tailscale funnel --https=443 off 2>$null | Out-Null
Start-Sleep -Seconds 1
& tailscale funnel --bg --yes "http://127.0.0.1:8791" | Out-Null
Start-Sleep -Seconds 2

# Stability check
Start-Sleep -Seconds 5
try {
  $h2 = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 3
  Write-Host ("stable local provider=" + $h2.llm_provider)
} catch {
  Write-Host "UNSTABLE: died within 5s"
  Get-Content $errLog -Tail 40
  exit 2
}
try {
  $h3 = Invoke-RestMethod "https://desktop-ibhgp7g.tailcc9705.ts.net/health" -TimeoutSec 20
  Write-Host ("public provider=" + $h3.llm_provider)
} catch {
  Write-Host ("public FAIL: " + $_.Exception.Message)
}

# Direct deepseek probe via hub chat requires token; probe upstream instead
$key = $env:DFTB_CLASS_DEEPSEEK_API_KEY
$model = if ($env:DFTB_CLASS_DEEPSEEK_MODEL) { $env:DFTB_CLASS_DEEPSEEK_MODEL } else { "deepseek-v4-flash" }
$payload = (@{
  model = $model
  messages = @(@{ role = "user"; content = "Reply with exactly: OK" })
  temperature = 0.0
  max_tokens = 64
} | ConvertTo-Json -Depth 5)
$r = Invoke-WebRequest -Uri "https://api.deepseek.com/chat/completions" -Method POST -TimeoutSec 60 `
  -Headers @{ Authorization = ("Bearer " + $key); "Content-Type" = "application/json" } `
  -Body $payload -UseBasicParsing
$j = $r.Content | ConvertFrom-Json
Write-Host ("deepseek_direct status=" + $r.StatusCode + " content=" + [string]$j.choices[0].message.content)
