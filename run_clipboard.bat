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
  echo [ERROR] No usable Python found. Set WECHAT_BOT_PYTHON to python.exe.
  pause
  exit /b 1
)

echo [INFO] Clipboard mode (no wxauto4 needed)
echo [INFO] Python: %PY_EXE%
echo [INFO] Select message in WeChat, press Ctrl+Q to generate reply
echo [INFO] Double-press Ctrl+Q (Ctrl+Q+Q) to generate + auto-paste into chat
echo [INFO] Ctrl+Shift+Q to exit
echo [INFO] Console: type correction rules directly, /fix for interactive mode
echo [INFO] Supports text + image mixed copy from WeChat
"%PY_EXE%" main.py
pause >nul 2>&1
