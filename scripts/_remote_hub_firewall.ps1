Write-Host "=== listen ==="
netstat -ano | findstr ":8791"
Write-Host "=== self via tailscale ip ==="
try { (Invoke-RestMethod "http://100.127.118.69:8791/health" -TimeoutSec 5 | ConvertTo-Json -Compress) }
catch { "via_ts_ip_fail=$($_.Exception.Message)" }
try { (Invoke-RestMethod "http://127.0.0.1:8791/health" -TimeoutSec 5 | ConvertTo-Json -Compress) }
catch { "via_loopback_fail=$($_.Exception.Message)" }

# ensure firewall rule for 8791
$rule = Get-NetFirewallRule -DisplayName "DFTB Classroom Hub 8791" -ErrorAction SilentlyContinue
if (-not $rule) {
  try {
    New-NetFirewallRule -DisplayName "DFTB Classroom Hub 8791" -Direction Inbound -Protocol TCP -LocalPort 8791 -Action Allow -Profile Any | Out-Null
    Write-Host "firewall_rule_created"
  } catch {
    Write-Host "firewall_rule_failed=$($_.Exception.Message)"
  }
} else {
  Write-Host "firewall_rule_exists"
}

Start-Sleep -Seconds 1
try { (Invoke-RestMethod "http://100.127.118.69:8791/health" -TimeoutSec 5 | ConvertTo-Json -Compress) }
catch { "after_fw_fail=$($_.Exception.Message)" }
