$ErrorActionPreference = "Continue"
Write-Host "listeners:"
Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue |
  Format-Table OwningProcess,LocalAddress -AutoSize
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='powershell.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "uvicorn|classroom_hub" } |
  ForEach-Object { Write-Host ("proc " + $_.ProcessId + " " + $_.Name + " :: " + $_.CommandLine.Substring(0, [Math]::Min(160, $_.CommandLine.Length))) }

foreach ($u in @(
  "http://127.0.0.1:8791/health",
  "http://100.127.118.69:8791/health",
  "https://desktop-ibhgp7g.tailcc9705.ts.net/health"
)) {
  try {
    $h = Invoke-RestMethod $u -TimeoutSec 15
    Write-Host ("OK " + $u + " provider=" + $h.llm_provider)
  } catch {
    Write-Host ("FAIL " + $u + " " + $_.Exception.Message)
  }
}
