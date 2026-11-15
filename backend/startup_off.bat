@echo off
REM ==== Stop Kageon from starting automatically at login ====
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$dir = [Environment]::GetFolderPath('Startup'); $found = $false;" ^
  "foreach ($n in 'Kageon.lnk','JARVIS.lnk') { $l = Join-Path $dir $n; if (Test-Path $l) { Remove-Item $l; $found = $true } };" ^
  "if ($found) { Write-Host 'Auto-start removed.' } else { Write-Host 'Auto-start was not enabled.' }"
pause
