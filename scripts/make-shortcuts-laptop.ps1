$W = New-Object -ComObject WScript.Shell
$desk = [Environment]::GetFolderPath("Desktop")
$stu = (Get-ChildItem "C:\Users\13919\AppData\Local\Programs\dftb-neu\*.exe" | Where-Object { $_.Name -notlike "Uninstall*" } | Select-Object -First 1).FullName
$tea = (Get-ChildItem "C:\Users\13919\AppData\Local\Programs\dftb-neu-teacher\*.exe" | Where-Object { $_.Name -notlike "Uninstall*" } | Select-Object -First 1).FullName
Write-Host "stu=$stu"
Write-Host "tea=$tea"
$s1 = $W.CreateShortcut("$desk\DFTB-Neu.lnk")
$s1.TargetPath = $stu
$s1.WorkingDirectory = Split-Path $stu
$s1.Save()
$s2 = $W.CreateShortcut("$desk\DFTB-Neu-Teacher.lnk")
$s2.TargetPath = $tea
$s2.WorkingDirectory = Split-Path $tea
$s2.Save()
Get-ChildItem "$desk\DFTB*.lnk" | ForEach-Object { Write-Host $_.Name }
Write-Host DONE
