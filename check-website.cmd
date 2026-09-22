@echo off
chcp 65001 >nul
echo [80번 포트 사용 상태]
netstat -ano | findstr LISTENING | findstr ":80 "
echo.
echo [로컬 HTTP 응답]
curl.exe -I --max-time 5 http://localhost/
echo.
echo [도메인 HTTP 응답]
curl.exe -I --max-time 10 http://ailab.cbnu.ac.kr/
pause
