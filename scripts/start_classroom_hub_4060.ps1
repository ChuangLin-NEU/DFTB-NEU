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
    if ($_ -match "^CMATS_MP_API_KEY=(.*)$") { $env:DFTB_CLASS_MP_API_KEY = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_PROVIDER=(.*)$") { $env:DFTB_CLASS_LLM_PROVIDER = $Matches[1].Trim() }
    if ($_ -match "^CMATS_DEEPSEEK_BASE_URL=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_BASE_URL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_DEEPSEEK_MODEL=(.*)$") { $env:DFTB_CLASS_DEEPSEEK_MODEL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_BASE_URL=(.*)$") { $env:DFTB_CLASS_LLM_BASE_URL = $Matches[1].Trim() }
    if ($_ -match "^CMATS_LLM_MODEL=(.*)$") { $env:DFTB_CLASS_LLM_MODEL = $Matches[1].Trim() }
  }
}
if (-not $env:DFTB_CLASS_LLM_PROVIDER) { $env:DFTB_CLASS_LLM_PROVIDER = "deepseek" }

New-Item -ItemType Directory -Force -Path "D:\dftb-neu\data\classroom" | Out-Null
New-Item -ItemType Directory -Force -Path "D:\dftb-neu\data" | Out-Null

$py = "D:\cmats-lab\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "D:\anaconda3\python.exe" }

$outLog = "D:\dftb-neu\data\classroom_hub.out.log"
$errLog = "D:\dftb-neu\data\classroom_hub.err.log"
"" | Set-Content -Path $outLog -Encoding utf8
"" | Set-Content -Path $errLog -Encoding utf8

# Detach uvicorn. PowerShell Start-Process redirects close when this script exits.
$spawnPy = 'D:\dftb-neu\data\classroom\spawn_hub.py'
@'
import subprocess, sys
py, out_path, err_path = sys.argv[1:]
out = open(out_path, "w", encoding="utf-8", errors="replace")
err = open(err_path, "w", encoding="utf-8", errors="replace")
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
base = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
argv = [py, "-m", "uvicorn", "classroom_hub.main:app",
        "--app-dir", r"D:\dftb-neu\apps", "--host", "0.0.0.0", "--port", "8791", "--no-use-colors"]
try:
    p = subprocess.Popen(argv, cwd=r"D:\dftb-neu", stdout=out, stderr=err,
                         stdin=subprocess.DEVNULL, creationflags=base | CREATE_BREAKAWAY_FROM_JOB)
except OSError:
    p = subprocess.Popen(argv, cwd=r"D:\dftb-neu", stdout=out, stderr=err,
                         stdin=subprocess.DEVNULL, creationflags=base)
print(p.pid)
'@ | Set-Content -Path $spawnPy -Encoding ascii
$spawned = (& $py $spawnPy $py $outLog $errLog | Select-Object -Last 1).ToString().Trim()
"started pid=$spawned" | Out-File -FilePath "D:\dftb-neu\data\classroom_hub.pid.txt" -Encoding ascii
Write-Output "started pid=$spawned"
