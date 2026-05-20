@echo off
REM Smart Farm AI Platform — 서비스 중지 스크립트 (Windows)

set NGINX=C:\nginx
set PGSQL=C:\PostgreSQL\pgsql

echo [Smart Farm] 서비스 중지 중...

REM nginx 중지
cd /d %NGINX%
nginx.exe -s quit 2>nul
echo [1/3] nginx 중지됨

REM FastAPI 중지
taskkill /FI "WINDOWTITLE eq smartfarm-api*" /F > nul 2>&1
echo [2/3] FastAPI 중지됨

REM PostgreSQL은 수동 중지 (데이터 보호)
echo [3/3] PostgreSQL 중지 (수동):
echo       %PGSQL%\bin\pg_ctl stop -D %PGSQL%\data

echo.
echo [Smart Farm] nginx, API 중지 완료. PostgreSQL은 수동으로 중지하세요.
