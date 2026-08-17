$ErrorActionPreference = "Continue"
$envPath = "D:\cmats-lab\.env"
$key = ""
Get-Content $envPath | ForEach-Object {
  if ($_ -match "^CMATS_DEEPSEEK_API_KEY=(.*)$") { $key = $Matches[1].Trim() }
}
$base = "https://api.deepseek.com"
$url = $base + "/chat/completions"
$models = @("deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner")
foreach ($model in $models) {
  Write-Host ("=== model=" + $model + " ===")
  $payload = (@{
    model = $model
    messages = @(@{ role = "user"; content = "Reply with exactly: OK" })
    temperature = 0.0
    max_tokens = 256
  } | ConvertTo-Json -Depth 5)
  try {
    $r = Invoke-WebRequest -Uri $url -Method POST -TimeoutSec 60 `
      -Headers @{ Authorization = ("Bearer " + $key); "Content-Type" = "application/json" } `
      -Body $payload -UseBasicParsing
    $j = $r.Content | ConvertFrom-Json
    $c = [string]$j.choices[0].message.content
    $rc = [string]$j.choices[0].message.reasoning_content
    Write-Host ("status=" + $r.StatusCode + " content_len=" + $c.Length + " reasoning_len=" + $rc.Length)
    Write-Host ("content=" + $c)
    Write-Host ("finish_reason=" + [string]$j.choices[0].finish_reason)
    if ($j.usage) {
      Write-Host ("usage prompt=" + $j.usage.prompt_tokens + " completion=" + $j.usage.completion_tokens + " total=" + $j.usage.total_tokens)
    }
  } catch {
    $resp = $_.Exception.Response
    if ($resp) {
      $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
      $txt = $reader.ReadToEnd()
      Write-Host ("FAIL status=" + [int]$resp.StatusCode)
      Write-Host ($txt.Substring(0, [Math]::Min(300, $txt.Length)))
    } else {
      Write-Host ("FAIL " + $_.Exception.Message)
    }
  }
}
