@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"

if not exist "runtime\python\python.exe" (
  echo Windows 무설치 ZIP의 압축을 먼저 풀어주세요.
  pause
  exit /b 1
)

"runtime\python\python.exe" "server\website_only.py"
if errorlevel 1 (
  echo.
  echo 실행에 실패했습니다. 80번 포트가 이미 사용 중인지 확인하세요.
  echo 확인 명령: netstat -ano ^| findstr :80
  pause
)
