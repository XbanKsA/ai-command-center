@echo off
REM ==== Make JARVIS start automatically (minimized) every time you log in to Windows ====
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo [ERROR] Run setup.bat first.
  pause & exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'JARVIS.lnk';" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk);" ^
  "$s.TargetPath = '%~dp0autostart.bat';" ^
  "$s.WorkingDirectory = '%~dp0';" ^
  "$s.WindowStyle = 7;" ^
  "$s.IconLocation = '%SystemRoot%\System32\shell32.dll,22';" ^
  "$s.Description = 'AI Command Center - JARVIS';" ^
  "$s.Save(); Write-Host ('Created: ' + $lnk)"
echo.
echo JARVIS will now start automatically (minimized) when you log in.
echo To turn it off again: startup_off.bat
pause
