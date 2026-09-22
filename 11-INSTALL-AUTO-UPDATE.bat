@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
if not exist "runtime\python\python.exe" (
  echo ERROR: Copy this addon into your existing portable website folder.
  pause
  exit /b 1
)
"runtime\python\python.exe" "server\update_website.py" --install
if errorlevel 1 (echo FAILED. See logs\website-update.log) else (echo DONE.)
pause
