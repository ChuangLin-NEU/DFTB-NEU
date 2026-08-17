# 在 4060（desktop-ibhgp7g）上运行：同步课堂中心代码并重启服务
# 用法（管理员 PowerShell 可选）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File D:\dftb-neu\scripts\sync_and_restart_hub_4060.ps1
# 或先指定源码目录：
#   $env:DFTB_NEU_SRC = 'C:\Users\13919\Projects\dftb-neu'

$ErrorActionPreference = "Stop"
$DestRoot = "D:\dftb-neu"
$SrcCandidates = @(
  $env:DFTB_NEU_SRC,
  "C:\Users\13919\Projects\dftb-neu",
  "D:\dftb-neu-src",
  (Join-Path $PSScriptRoot "..")
) | Where-Object { $_ -and (Test-Path $_) }

$Src = $null
foreach ($c in $SrcCandidates) {
  $hub = Join-Path $c "apps\classroom_hub\main.py"
  if (Test-Path $hub) { $Src = (Resolve-Path $c).Path; break }
}
if (-not $Src) {
  throw "未找到源码（需含 apps\classroom_hub\main.py）。请设置 DFTB_NEU_SRC。"
}

Write-Host "SRC=$Src"
Write-Host "DST=$DestRoot"

New-Item -ItemType Directory -Force -Path "$DestRoot\apps\classroom_hub" | Out-Null
New-Item -ItemType Directory -Force -Path "$DestRoot\scripts" | Out-Null
New-Item -ItemType Directory -Force -Path "$DestRoot\data\classroom" | Out-Null

Copy-Item "$Src\apps\classroom_hub\*" "$DestRoot\apps\classroom_hub\" -Recurse -Force
Copy-Item "$Src\scripts\run_classroom_hub_4060.*" "$DestRoot\scripts\" -Force -ErrorAction SilentlyContinue
Copy-Item "$Src\scripts\start_classroom_hub_4060.ps1" "$DestRoot\scripts\" -Force -ErrorAction SilentlyContinue
Copy-Item "$Src\scripts\restart_classroom_hub_4060.bat" "$DestRoot\scripts\" -Force -ErrorAction SilentlyContinue
Copy-Item "$Src\scripts\sync_and_restart_hub_4060.ps1" "$DestRoot\scripts\" -Force

if (-not (Select-String -Path "$DestRoot\apps\classroom_hub\main.py" -Pattern "teacher/gate/clear" -Quiet)) {
  throw "同步后仍缺少 /teacher/gate/clear，中止重启。"
}

Write-Host "Stopping listeners on 8791..."
Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$env:DFTB_CLASS_HOST = "0.0.0.0"
$env:DFTB_CLASS_PORT = "8791"
$env:DFTB_CLASS_DATA = "$DestRoot\data\classroom"
if (-not $env:DFTB_CLASS_TEACHER_PASSWORD) { $env:DFTB_CLASS_TEACHER_PASSWORD = "zl303@" }
if (-not $env:DFTB_CLASS_ADMIN_SECRET) { $env:DFTB_CLASS_ADMIN_SECRET = $env:DFTB_CLASS_TEACHER_PASSWORD }
if (-not $env:DFTB_CLASS_TOKEN_SECRET) { $env:DFTB_CLASS_TOKEN_SECRET = $env:DFTB_CLASS_TEACHER_PASSWORD }

# 从本机 cmats-lab/.env 注入 DeepSeek 等密钥（不打印）
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

$pyCandidates = @(
  "D:\cmats-lab\.venv\Scripts\python.exe",
  "D:\anaconda3\python.exe",
  "C:\Users\13919\Projects\dftb-neu\.venv\Scripts\python.exe",
  (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
) | Where-Object { $_ -and (Test-Path $_) }
$py = $pyCandidates | Select-Object -First 1
if (-not $py) { throw "未找到 Python，无法启动课堂中心。" }

$outLog = "$DestRoot\data\classroom_hub.out.log"
$errLog = "$DestRoot\data\classroom_hub.err.log"
"" | Set-Content $outLog -Encoding utf8
"" | Set-Content $errLog -Encoding utf8

$argList = @(
  "-m", "uvicorn", "classroom_hub.main:app",
  "--app-dir", "$DestRoot\apps",
  "--host", "0.0.0.0",
  "--port", "8791"
)
$p = Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $DestRoot `
  -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
"started pid=$($p.Id)" | Set-Content "$DestRoot\data\classroom_hub.pid.txt" -Encoding ascii
Write-Host "started pid=$($p.Id) python=$py"

Start-Sleep -Seconds 3
try {
  $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
  Write-Host ("health ok llm_configured=" + $h.llm_configured + " provider=" + $h.llm_provider)
} catch {
  Write-Host "health check failed: $($_.Exception.Message)"
  Write-Host "--- err log ---"
  Get-Content $errLog -ErrorAction SilentlyContinue | Select-Object -Last 40
  throw
}

# 计划任务保活
schtasks /Delete /TN dftb-classroom-hub /F 2>$null | Out-Null
$tr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$DestRoot\scripts\start_classroom_hub_4060.ps1`""
schtasks /Create /TN dftb-classroom-hub /TR $tr /SC ONLOGON /RL LIMITED /F | Out-Null
Write-Host "sync_and_restart_done"
