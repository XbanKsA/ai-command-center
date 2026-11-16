@echo off
REM ==== Make Kageon start automatically every time you log in to Windows ====
REM It runs in the system tray (crescent icon near the clock) - no window that can be closed by mistake.
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo [ERROR] Run setup.bat first.
  pause & exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$old = Join-Path ([Environment]::GetFolderPath('Startup')) 'JARVIS.lnk'; if (Test-Path $old) { Remove-Item $old };" ^
  "$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Kageon.lnk';" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk);" ^
  "$s.TargetPath = '%~dp0.venv\Scripts\pythonw.exe';" ^
  "$s.Arguments = 'main.py --autostart';" ^
  "$s.WorkingDirectory = '%~dp0';" ^
  "$s.IconLocation = '%SystemRoot%\System32\shell32.dll,22';" ^
  "$s.Description = 'Kageon';" ^
  "$s.Save(); Write-Host ('Created: ' + $lnk)"
echo.
echo Kageon will now start automatically in the system tray when you log in.
echo Look for the crescent icon near the clock (click ^^ if it's hidden). Right-click it to quit.
echo To turn it off again: startup_off.bat
pause
