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
  pause
  exit /b 1
)

echo [INFO] Python: %PY_EXE%
echo [1] 检查 wxauto4 ...
"%PY_EXE%" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('wxauto') or importlib.util.find_spec('wxauto4') else 1)" >nul 2>&1
if errorlevel 1 (
  echo [WARN] 当前 Python 未安装 wxauto4；如需 PC 微信自动化，请手动执行:
  echo        "%PY_EXE%" -m pip install wxauto4
) else (
  echo [OK] wxauto4/wxauto 可用
)
echo [2] 启动微信自动回复（请先登录 PC 微信）...
"%PY_EXE%" main.py
pause
