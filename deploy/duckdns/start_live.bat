@echo off
REM ===== KAASA SmartOS — DuckDNS 무료 도메인 상시 공개 (자동 HTTPS) =====
REM 사전(사용자): 1) duckdns.org 가입·서브도메인 생성·토큰 확보
REM               2) Caddyfile 의 {SUBDOMAIN} 치환, duckdns_update.ps1 값 입력
REM               3) 공유기 포트포워딩 80,443 → 이 PC
REM               4) caddy.exe 를 deploy\duckdns\ 에 배치 (https://caddyserver.com/download)
set SMART_FARM=C:\smart_farm
set PYTHON=C:\tools\python311\python.exe
cd /d %SMART_FARM%

REM (선택) 실서비스면 PUBLIC_DEMO 해제, 데모면 1 유지
REM set PUBLIC_DEMO=1
set JWT_SECRET_KEY=CHANGE_ME_RANDOM_LONG_SECRET
set PYTHONPATH=%SMART_FARM%
set PYTHONIOENCODING=utf-8

REM 1) API 기동 (백그라운드)
start "kaasa-api" /MIN %PYTHON% -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level warning
timeout /t 5 /nobreak >nul

REM 2) DuckDNS IP 1회 갱신 (이후 스케줄러가 5분 주기)
powershell -ExecutionPolicy Bypass -File deploy\duckdns\duckdns_update.ps1

REM 3) Caddy 자동 HTTPS 리버스 프록시 (Let's Encrypt 자동 발급)
deploy\duckdns\caddy.exe run --config deploy\duckdns\Caddyfile

REM 완료 후: https://{SUBDOMAIN}.duckdns.org/intro 로 공개 HTTPS 접속
