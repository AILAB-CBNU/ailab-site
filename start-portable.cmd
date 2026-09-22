@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
"runtime\python\python.exe" "server\portable_launcher.py"
if errorlevel 1 (
  echo.
  echo 실행에 실패했습니다. 위 오류와 logs 폴더를 확인하세요.
  pause
)
