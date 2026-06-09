@echo off
REM ===== KAASA SmartOS — Cloudflare Named Tunnel 상시 공개 (포트포워딩 불필요) =====
REM 사전(named_tunnel_runbook.md): tunnel login/create/route + config.yml {TUNNEL_ID}{DOMAIN} 치환
set SMART_FARM=C:\smart_farm
set PYTHON=C:\tools\python311\python.exe
set CF=%SMART_FARM%\deploy\cloudflare\bin\cloudflared.exe
cd /d %SMART_FARM%

REM 데모면 1 유지 / 실서비스면 아래 줄 주석
set PUBLIC_DEMO=1
set JWT_SECRET_KEY=CHANGE_ME_RANDOM_LONG_SECRET
set PYTHONPATH=%SMART_FARM%
set PYTHONIOENCODING=utf-8

REM 1) API 기동
start "kaasa-api" /MIN %PYTHON% -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level warning
timeout /t 5 /nobreak >nul

REM 2) Named tunnel 실행 (config.yml 사용)
"%CF%" tunnel --config deploy\cloudflare\config.yml run kaasa-smartos
