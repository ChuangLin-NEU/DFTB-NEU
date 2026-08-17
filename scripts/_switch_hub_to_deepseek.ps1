# Run on hub host: set provider=deepseek, restart hub, probe chat
$ErrorActionPreference = "Stop"
$envPath = "D:\cmats-lab\.env"
if (-not (Test-Path $envPath)) { throw "missing $envPath" }

$raw = Get-Content $envPath -Raw
if ($raw -match "(?m)^CMATS_LLM_PROVIDER=.*$") {
  $raw = [regex]::Replace($raw, "(?m)^CMATS_LLM_PROVIDER=.*$", "CMATS_LLM_PROVIDER=deepseek")
} else {
  $raw = $raw.TrimEnd() + "`r`nCMATS_LLM_PROVIDER=deepseek`r`n"
}
[System.IO.File]::WriteAllText($envPath, $raw)
Write-Host "set CMATS_LLM_PROVIDER=deepseek"

$sec = "D:\dftb-neu\data\classroom\secrets.env"
if (Test-Path $sec) {
  $sraw = Get-Content $sec -Raw
  if ($sraw -match "(?m)^DFTB_CLASS_LLM_PROVIDER=.*$") {
    $sraw = [regex]::Replace($sraw, "(?m)^DFTB_CLASS_LLM_PROVIDER=.*$", "DFTB_CLASS_LLM_PROVIDER=deepseek")
  } elseif ($sraw -match "(?m)^CMATS_LLM_PROVIDER=.*$") {
    $sraw = [regex]::Replace($sraw, "(?m)^CMATS_LLM_PROVIDER=.*$", "CMATS_LLM_PROVIDER=deepseek")
  } else {
    $sraw = $sraw.TrimEnd() + "`r`nDFTB_CLASS_LLM_PROVIDER=deepseek`r`n"
  }
  [System.IO.File]::WriteAllText($sec, $sraw)
  Write-Host "updated secrets.env"
}

Write-Host "restarting hub..."
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\dftb-neu\scripts\start_classroom_hub_4060.ps1"
Start-Sleep -Seconds 4
$h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
Write-Host ("health provider=" + $h.llm_provider + " ds=" + $h.deepseek_key_set + " qw=" + $h.qwen_key_set)

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
Import-HubEnvFile $sec
Get-Content $envPath | ForEach-Object {
  if ($_ -match "^CMATS_DEEPSEEK_API_KEY=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_API_KEY = $Matches[1].Trim() }
  if ($_ -match "^CMATS_DEEPSEEK_BASE_URL=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_BASE_URL = $Matches[1].Trim() }
  if ($_ -match "^CMATS_DEEPSEEK_MODEL=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_MODEL = $Matches[1].Trim() }
}
$key = $env:DFTB_CLASS_DEEPSEEK_API_KEY
$base = if ($env:DFTB_CLASS_DEEPSEEK_BASE_URL) { $env:DFTB_CLASS_DEEPSEEK_BASE_URL.TrimEnd("/") } else { "https://api.deepseek.com" }
$model = if ($env:DFTB_CLASS_DEEPSEEK_MODEL) { $env:DFTB_CLASS_DEEPSEEK_MODEL } else { "deepseek-chat" }
$url = $base + "/chat/completions"
$payloadObj = @{
  model = $model
  messages = @(
    @{ role = "system"; content = "Be concise." },
    @{ role = "user"; content = "Reply with exactly: OK" }
  )
  temperature = 0.0
  max_tokens = 16
}
$payload = $payloadObj | ConvertTo-Json -Depth 5
Write-Host ("probe url=" + $url + " model=" + $model)
$r = Invoke-WebRequest -Uri $url -Method POST -TimeoutSec 60 `
  -Headers @{ Authorization = ("Bearer " + $key); "Content-Type" = "application/json" } `
  -Body $payload -UseBasicParsing
Write-Host ("status=" + $r.StatusCode)
$j = $r.Content | ConvertFrom-Json
$c = [string]$j.choices[0].message.content
Write-Host ("content_len=" + $c.Length)
Write-Host ("content=" + $c)
Write-Host ("finish_reason=" + [string]$j.choices[0].finish_reason)
