@echo off
REM ==== Stop JARVIS from starting automatically at login ====
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'JARVIS.lnk';" ^
  "if (Test-Path $lnk) { Remove-Item $lnk; Write-Host 'Auto-start removed.' } else { Write-Host 'Auto-start was not enabled.' }"
pause
