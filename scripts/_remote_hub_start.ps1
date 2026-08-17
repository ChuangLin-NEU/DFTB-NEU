$ErrorActionPreference = "Continue"
Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

$env:DFTB_CLASS_HOST = "0.0.0.0"
$env:DFTB_CLASS_PORT = "8791"
$env:DFTB_CLASS_DATA = "D:\dftb-neu\data\classroom"
$env:DFTB_CLASS_TEACHER_PASSWORD = "zl303@"
$env:DFTB_CLASS_ADMIN_SECRET = "zl303@"
$env:DFTB_CLASS_TOKEN_SECRET = "zl303@"
$env:PYTHONPATH = "D:\dftb-neu\apps"
$env:DFTB_CLASS_LLM_PROVIDER = "deepseek"

if (Test-Path "D:\cmats-lab\.env") {
  Get-Content "D:\cmats-lab\.env" | ForEach-Object {
    if ($_ -match "^CMATS_DEEPSEEK_API_KEY=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_API_KEY=(.*)$") { $env:DFTB_CLASS_LLM_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_MP_API_KEY=(.*)$") { $env:DFTB_CLASS_MP_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_PROVIDER=(.*)$") { $env:DFTB_CLASS_LLM_PROVIDER = $Matches[1].Trim() }
    if ($_ -match "^CMATS_DEEPSEEK_BASE_URL=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_BASE_URL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_DEEPSEEK_MODEL=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_MODEL = $Matches[1].Trim() }
  }
}

New-Item -ItemType Directory -Force -Path "D:\dftb-neu\data\classroom" | Out-Null
$py = "D:\cmats-lab\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "C:\Users\Focalors\AppData\Local\Programs\Python\Python312\python.exe" }

Write-Host "python=$py"
Write-Host "deepseek_key_set=$([bool]$env:DFTB_CLASS_DEEPSEEK_API_KEY)"

# smoke import first
& $py -c "import sys; sys.path.insert(0,r'D:\dftb-neu\apps'); import classroom_hub.main as m; print('import_ok', hasattr(m,'teacher_clear_gate'))"
if ($LASTEXITCODE -ne 0) { throw "import failed" }

$outLog = "D:\dftb-neu\data\classroom_hub.out.log"
$errLog = "D:\dftb-neu\data\classroom_hub.err.log"
"" | Set-Content $outLog -Encoding utf8
"" | Set-Content $errLog -Encoding utf8

$argList = @(
  "-m", "uvicorn", "classroom_hub.main:app",
  "--app-dir", "D:\dftb-neu\apps",
  "--host", "0.0.0.0",
  "--port", "8791"
)
$p = Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory "D:\dftb-neu" `
  -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
"started pid=$($p.Id)" | Set-Content "D:\dftb-neu\data\classroom_hub.pid.txt" -Encoding ascii
Write-Host "started pid=$($p.Id)"
Start-Sleep -Seconds 4
Write-Host "alive=$(-not $p.HasExited) exit=$($p.ExitCode)"
Write-Host "---ERR---"
Get-Content $errLog -Tail 40 -ErrorAction SilentlyContinue
Write-Host "---OUT---"
Get-Content $outLog -Tail 20 -ErrorAction SilentlyContinue
try {
  $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
  Write-Host ("health=" + ($h | ConvertTo-Json -Compress))
} catch {
  Write-Host ("health_fail=" + $_.Exception.Message)
}
