@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
if not exist "runtime\python\python.exe" (
  echo ERROR: Extract this addon into the existing portable website folder.
  pause
  exit /b 1
)
"runtime\python\python.exe" "discord_sync\setup_briefing.py"
pause
