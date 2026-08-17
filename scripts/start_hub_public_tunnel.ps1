# Deprecated: localhost.run temporary tunnel retired.
# Use Tailscale Funnel (fixed HTTPS) instead.
$ErrorActionPreference = "Stop"
Write-Warning "start_hub_public_tunnel.ps1 已停用（localhost.run）。改走 scripts\\start_hub_funnel.ps1"
& (Join-Path $PSScriptRoot "start_hub_funnel.ps1")
