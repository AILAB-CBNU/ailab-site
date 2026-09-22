@echo off
chcp 65001 >nul

net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo 이 파일을 우클릭한 뒤 "관리자 권한으로 실행"을 선택하세요.
  pause
  exit /b 1
)

netsh advfirewall firewall delete rule name="CBNU AI Lab HTTP" >nul 2>&1
netsh advfirewall firewall add rule name="CBNU AI Lab HTTP" dir=in action=allow protocol=TCP localport=80 profile=any
if errorlevel 1 (
  echo 방화벽 규칙 생성에 실패했습니다.
  pause
  exit /b 1
)

echo Windows 방화벽에서 TCP 80 포트를 허용했습니다.
pause
