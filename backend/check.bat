@echo off
REM ==== Pre-flight check: GPU, Ollama, app discovery, mic, speech-to-text, voice ====
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python tools\check_setup.py %*
pause
