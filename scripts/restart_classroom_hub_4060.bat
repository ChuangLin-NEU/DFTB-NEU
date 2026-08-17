@echo off
setlocal
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
ping -n 2 127.0.0.1 >nul
if not exist "D:\dftb-neu\data" mkdir "D:\dftb-neu\data"
if not exist "D:\dftb-neu\data\classroom" mkdir "D:\dftb-neu\data\classroom"
schtasks /Delete /TN dftb-classroom-hub /F >nul 2>&1
schtasks /Create /TN dftb-classroom-hub /TR "D:\dftb-neu\scripts\run_classroom_hub_4060.bat" /SC ONLOGON /RL LIMITED /F
schtasks /Run /TN dftb-classroom-hub
ping -n 8 127.0.0.1 >nul
echo classroom_hub_restarted
endlocal
