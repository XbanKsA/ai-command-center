@echo off
REM ==== OPTIONAL: run speech recognition (Whisper) on the NVIDIA GPU instead of the CPU ====
REM Installs NVIDIA's CUDA math + cuDNN libraries into the project's .venv (about 1 GB download).
REM If your GPU isn't supported by them, Kageon automatically keeps using the CPU - nothing breaks.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
echo.
echo Done. Run check.bat - the "Speech-to-text" line should now say CUDA instead of CPU.
pause
