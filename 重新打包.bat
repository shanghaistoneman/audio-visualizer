@echo off
cd /d "%~dp0"
set "PY=C:\Python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 goto nopyi
"%PY%" -m PyInstaller --clean --noconfirm audio_visualizer.spec
if errorlevel 1 goto fail
echo.
echo Done. Check the dist folder for the EXE file.
pause
exit /b 0
:nopyi
echo PyInstaller not found. Install it:
echo   "%PY%" -m pip install pyinstaller
pause
exit /b 1
:fail
echo.
echo Build failed.
pause
exit /b 1
