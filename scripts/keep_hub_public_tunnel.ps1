# Deprecated: localhost.run keeper retired.
# Use Tailscale Funnel keeper instead.
$ErrorActionPreference = "Stop"
Write-Warning "keep_hub_public_tunnel.ps1 已停用（localhost.run）。改走 scripts\\keep_hub_funnel.ps1"
& (Join-Path $PSScriptRoot "keep_hub_funnel.ps1")
