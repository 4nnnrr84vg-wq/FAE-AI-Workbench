@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
if not exist ".venv312\Scripts\python.exe" (
  echo [INFO] Creating .venv312 ...
  py -3.12 -m venv .venv312 >nul 2>&1
  if errorlevel 1 (
    python -m venv .venv312
  )
)
if not exist ".venv312\Scripts\python.exe" (
  echo [ERROR] Failed to create .venv312. Please install Python 3.12.
  pause
  exit /b 1
)
".venv312\Scripts\python.exe" -m pip install -r apps\backend\requirements.txt
pause
