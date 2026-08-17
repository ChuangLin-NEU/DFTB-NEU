Get-Content "D:\dftb-neu\data\classroom_hub.out.log" -Tail 30 -ErrorAction SilentlyContinue
Write-Host "===="
Get-Content "D:\dftb-neu\data\classroom_hub.err.log" -Tail 30 -ErrorAction SilentlyContinue
