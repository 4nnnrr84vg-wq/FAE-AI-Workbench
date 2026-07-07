@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0set_api_key.ps1"
pause
