@echo off
cd /d "%~dp0"
set "PY=C:\Python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -c "import numpy, PIL, tkinter, imageio_ffmpeg" >nul 2>nul
if not errorlevel 1 goto run
echo Installing dependencies, please wait...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto fail
:run
"%PY%" -m audio_visualizer.gui
if errorlevel 1 goto fail
exit /b 0
:fail
echo.
echo Failed to start. Please run: pip install -r requirements.txt
pause
exit /b 1
