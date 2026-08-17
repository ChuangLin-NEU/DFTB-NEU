$ErrorActionPreference = "Continue"
try {
  $h = Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5
  Write-Host ("health ok=" + $h.ok + " llm=" + $h.llm_configured + " deepseek=" + $h.deepseek_key_set)
} catch {
  Write-Host ("health FAIL: " + $_.Exception.Message)
}
$pwd = $env:DFTB_CLASS_TEACHER_PASSWORD
if (-not $pwd) { $pwd = "zl303@" }
try {
  $r = Invoke-WebRequest "http://127.0.0.1:8791/teacher/gate" -Headers @{ "X-Teacher-Password" = $pwd } -UseBasicParsing -TimeoutSec 5
  Write-Host ("gate status=" + $r.StatusCode + " body=" + $r.Content)
} catch {
  Write-Host ("gate FAIL: " + $_.Exception.Message)
}
try {
  $body = '{"current_password":"' + $pwd + '","new_password":"' + $pwd + '"}'
  Invoke-WebRequest "http://127.0.0.1:8791/teacher/password" -Method POST -Headers @{ "X-Teacher-Password" = $pwd; "Content-Type" = "application/json" } -Body $body -UseBasicParsing -TimeoutSec 5 | Out-Null
  Write-Host "password endpoint unexpected success"
} catch {
  Write-Host ("password endpoint reachable: " + $_.Exception.Message)
}
Select-String -Path "D:\dftb-neu\apps\classroom_hub\main.py" -Pattern "code_plain|teacher/password" |
  ForEach-Object { Write-Host ("src: " + $_.Line.Trim()) }
