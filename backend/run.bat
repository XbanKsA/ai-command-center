@echo off
REM ==== Start the Kageon core server ====
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py
pause
