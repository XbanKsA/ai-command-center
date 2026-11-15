@echo off
REM ==== Kageon - one-time setup (Windows) ====
cd /d "%~dp0"
echo Creating virtual environment in backend\.venv ...
where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
if errorlevel 1 (
  echo [ERROR] Could not create the virtual environment. Is Python 3.11+ installed and on PATH?
  pause & exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
if errorlevel 1 (
  echo [ERROR] Package installation failed - see the messages above.
  pause & exit /b 1
)
if not exist .env copy .env.example .env >nul
echo.
echo ============================================================
echo  Setup complete.
echo  Next:  check.bat   (verifies everything + downloads voice models)
echo  Then:  run.bat     (starts Kageon)
echo ============================================================
pause
