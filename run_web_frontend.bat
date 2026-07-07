@echo off
cd /d "%~dp0\apps\frontend"
if not exist "node_modules" (
  call npm.cmd install --cache .npm-cache
)
call npm.cmd run dev -- --hostname 127.0.0.1 --port 3000
pause
