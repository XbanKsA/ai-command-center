@echo off
REM ==== Old auto-start entry point. startup_on.bat now starts Kageon directly with pythonw.exe (no window). ====
REM This file stays so an older Startup shortcut still works: it starts Kageon in the tray and closes at once.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" main.py --autostart
