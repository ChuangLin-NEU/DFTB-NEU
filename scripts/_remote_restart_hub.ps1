$ErrorActionPreference = "Stop"
Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$env:DFTB_CLASS_HOST = "0.0.0.0"
$env:DFTB_CLASS_PORT = "8791"
$env:DFTB_CLASS_DATA = "D:\dftb-neu\data\classroom"
if (-not $env:DFTB_CLASS_TEACHER_PASSWORD) { $env:DFTB_CLASS_TEACHER_PASSWORD = "zl303@" }
$env:DFTB_CLASS_ADMIN_SECRET = $env:DFTB_CLASS_TEACHER_PASSWORD
if (-not $env:DFTB_CLASS_TOKEN_SECRET) { $env:DFTB_CLASS_TOKEN_SECRET = $env:DFTB_CLASS_TEACHER_PASSWORD }

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
foreach ($envFile in @("D:\cmats-lab\.env", "C:\Users\13919\Projects\cmats-lab\.env")) {
  if (-not (Test-Path $envFile)) { continue }
  Get-Content $envFile | ForEach-Object {
    if ($_ -match "^CMATS_DEEPSEEK_API_KEY=(.+)$") { $env:DFTB_CLASS_DEEPSEEK_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_API_KEY=(.+)$") { $env:DFTB_CLASS_LLM_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_MP_API_KEY=(.+)$") { $env:DFTB_CLASS_MP_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_PROVIDER=(.+)$") { $env:DFTB_CLASS_LLM_PROVIDER = $Matches[1].Trim() }
    if ($_ -match "^CMATS_DEEPSEEK_BASE_URL=(.+)$") { $env:DFTB_CLASS_DEEPSEEK_BASE_URL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_DEEPSEEK_MODEL=(.+)$") { $env:DFTB_CLASS_DEEPSEEK_MODEL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_BASE_URL=(.+)$") { $env:DFTB_CLASS_LLM_BASE_URL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_MODEL=(.+)$") { $env:DFTB_CLASS_LLM_MODEL = $Matches[1].Trim() }
  }
  break
}
if (-not $env:DFTB_CLASS_LLM_PROVIDER) { $env:DFTB_CLASS_LLM_PROVIDER = "deepseek" }

$py = "D:\cmats-lab\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$argList = @(
  "-m", "uvicorn", "classroom_hub.main:app",
  "--app-dir", "D:\dftb-neu\apps",
  "--host", "0.0.0.0",
  "--port", "8791"
)
$outLog = "D:\dftb-neu\data\classroom_hub.out.log"
$errLog = "D:\dftb-neu\data\classroom_hub.err.log"
$p = Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory "D:\dftb-neu" `
  -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
Start-Sleep -Seconds 4
try {
  $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
  Write-Host ("health ok llm_configured=" + $h.llm_configured + " deepseek_key_set=" + $h.deepseek_key_set + " mp_key_set=" + $h.mp_key_set)
} catch {
  Write-Host ("health FAIL: " + $_.Exception.Message)
  Get-Content $errLog -ErrorAction SilentlyContinue | Select-Object -Last 20
}
Write-Host ("pid=" + $p.Id)
