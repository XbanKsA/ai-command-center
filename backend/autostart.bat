@echo off
REM ==== Launched automatically at Windows login (see startup_on.bat). Don't run by hand - use run.bat ====
title JARVIS - AI Command Center
cd /d "%~dp0"
REM give Windows a few seconds to bring up Wi-Fi, audio and Ollama
timeout /t 15 /nobreak >nul
call .venv\Scripts\activate.bat
python main.py
