@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set "PY_EXE="
if defined WECHAT_BOT_PYTHON (
  if exist "%WECHAT_BOT_PYTHON%" set "PY_EXE=%WECHAT_BOT_PYTHON%"
)
if not defined PY_EXE (
  if exist ".venv312\Scripts\python.exe" (
    ".venv312\Scripts\python.exe" --version >nul 2>&1
    if not errorlevel 1 set "PY_EXE=.venv312\Scripts\python.exe"
  )
)
if not defined PY_EXE (
  if exist "D:\python\python.exe" set "PY_EXE=D:\python\python.exe"
)
if not defined PY_EXE set "PY_EXE=python"

"%PY_EXE%" import_style.py %*
pause
