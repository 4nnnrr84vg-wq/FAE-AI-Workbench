@echo off
setlocal
cd /d "%~dp0"
if exist ".venv312\Scripts\python.exe" (
  ".venv312\Scripts\python.exe" scripts\reindex_kb.py
) else (
  python scripts\reindex_kb.py
)
pause
