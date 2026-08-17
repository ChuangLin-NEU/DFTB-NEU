# Run on hub host (4060): probe LLM provider + DeepSeek/Qwen without printing secrets
$ErrorActionPreference = "Continue"

function Mask-Line([string]$line) {
  if ($line -match "^(.*?)=(.*)$") { return "$($Matches[1])=***len=$($Matches[2].Length)" }
  return $line
}

Write-Host "=== health ==="
try {
  $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
  Write-Host ("provider=" + $h.llm_provider)
  Write-Host ("deepseek_key_set=" + $h.deepseek_key_set)
  Write-Host ("qwen_key_set=" + $h.qwen_key_set)
  Write-Host ("llm_configured=" + $h.llm_configured)
} catch {
  Write-Host ("health FAIL: " + $_.Exception.Message)
}

Write-Host "=== env files (masked) ==="
foreach ($p in @(
  "D:\dftb-neu\data\classroom\secrets.env",
  "D:\cmats-lab\.env"
)) {
  Write-Host ("-- " + $p)
  if (-not (Test-Path $p)) { Write-Host "missing"; continue }
  Select-String -Path $p -Pattern "PROVIDER|DEEPSEEK|LLM_API|LLM_MODEL|LLM_BASE|CMATS_LLM" |
    ForEach-Object { Write-Host (Mask-Line $_.Line.Trim()) }
}

# Load keys into process env the same way hub start does
function Import-HubEnvFile([string]$path) {
  if (-not (Test-Path $path)) { return }
  Get-Content $path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    if ($line -match "^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
      $k = $Matches[1]
      $v = $Matches[2].Trim().Trim('"').Trim("'")
      Set-Item -Path "Env:$k" -Value $v
    }
  }
}
Import-HubEnvFile "D:\dftb-neu\data\classroom\secrets.env"
if (Test-Path "D:\cmats-lab\.env") {
  Get-Content "D:\cmats-lab\.env" | ForEach-Object {
    if ($_ -match "^CMATS_DEEPSEEK_API_KEY=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_API_KEY=(.*)$") { $env:DFTB_CLASS_LLM_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_PROVIDER=(.*)$") { $env:DFTB_CLASS_LLM_PROVIDER = $Matches[1].Trim() }
    if ($_ -match "^CMATS_DEEPSEEK_BASE_URL=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_BASE_URL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_DEEPSEEK_MODEL=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_MODEL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_BASE_URL=(.*)$") { $env:DFTB_CLASS_LLM_BASE_URL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_MODEL=(.*)$") { $env:DFTB_CLASS_LLM_MODEL = $Matches[1].Trim() }
  }
}

$dsKey = ($env:DFTB_CLASS_DEEPSEEK_API_KEY | ForEach-Object { $_ }).Trim()
$qwKey = ($env:DFTB_CLASS_LLM_API_KEY | ForEach-Object { $_ }).Trim()
$dsBase = if ($env:DFTB_CLASS_DEEPSEEK_BASE_URL) { $env:DFTB_CLASS_DEEPSEEK_BASE_URL.TrimEnd("/") } else { "https://api.deepseek.com" }
$dsModel = if ($env:DFTB_CLASS_DEEPSEEK_MODEL) { $env:DFTB_CLASS_DEEPSEEK_MODEL } else { "deepseek-v4-flash" }
$qwBase = if ($env:DFTB_CLASS_LLM_BASE_URL) { $env:DFTB_CLASS_LLM_BASE_URL.TrimEnd("/") } else { "https://dashscope.aliyuncs.com/compatible-mode/v1" }
$qwModel = if ($env:DFTB_CLASS_LLM_MODEL) { $env:DFTB_CLASS_LLM_MODEL } else { "qwen3.7-plus" }
$provFile = if ($env:DFTB_CLASS_LLM_PROVIDER) { $env:DFTB_CLASS_LLM_PROVIDER } else { "(unset→deepseek)" }
Write-Host ("file_provider=" + $provFile)
Write-Host ("ds_key_len=" + $dsKey.Length + " qw_key_len=" + $qwKey.Length)
Write-Host ("ds_model=" + $dsModel + " qw_model=" + $qwModel)

function Test-Chat([string]$name, [string]$key, [string]$url, [string]$model) {
  Write-Host ("=== probe " + $name + " model=" + $model + " ===")
  if (-not $key) { Write-Host "SKIP no key"; return }
  $payload = @{
    model = $model
    messages = @(@{ role = "user"; content = "Reply with exactly: ok" })
    temperature = 0.0
    max_tokens = 8
  } | ConvertTo-Json -Depth 5
  try {
    $r = Invoke-WebRequest -Uri $url -Method POST -TimeoutSec 45 `
      -Headers @{ Authorization = "Bearer $key"; "Content-Type" = "application/json" } `
      -Body $payload -UseBasicParsing
    Write-Host ("OK status=" + $r.StatusCode)
    $j = $r.Content | ConvertFrom-Json
    $content = $j.choices[0].message.content
    Write-Host ("content=" + $content)
  } catch {
    $resp = $_.Exception.Response
    if ($resp) {
      try {
        $stream = $resp.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $txt = $reader.ReadToEnd()
      } catch { $txt = "" }
      Write-Host ("FAIL status=" + [int]$resp.StatusCode)
      if ($txt) { Write-Host ($txt.Substring(0, [Math]::Min(400, $txt.Length))) }
    } else {
      Write-Host ("FAIL " + $_.Exception.Message)
    }
  }
}

$dsUrl = if ($dsBase.EndsWith("/v1")) { "$dsBase/chat/completions" } else { "$dsBase/chat/completions" }
if ($dsBase -notmatch "/v1$" -and $dsBase -match "deepseek.com") { $dsUrl = "$dsBase/chat/completions" }
$qwUrl = if ($qwBase.EndsWith("/v1")) { "$qwBase/chat/completions" } else { "$qwBase/v1/chat/completions" }

Test-Chat "deepseek" $dsKey $dsUrl $dsModel
Test-Chat "qwen/dashscope" $qwKey $qwUrl $qwModel
