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
if not defined PY_EXE (
  where python >nul 2>&1
  if not errorlevel 1 set "PY_EXE=python"
)
if not defined PY_EXE (
  echo [ERROR] 未找到可用 Python。可设置 WECHAT_BOT_PYTHON 指向 python.exe。
  exit /b 1
)

echo [INFO] Python: %PY_EXE%
"%PY_EXE%" main.py %*
