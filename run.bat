@echo off
REM Double-click to start. Installs deps if missing, then launches the app.
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install Python 3.10+ from python.org first.
  pause
  exit /b 1
)
python -m pip install --quiet --upgrade -r "%~dp0requirements.txt"
python "%~dp0app.py"
pause
