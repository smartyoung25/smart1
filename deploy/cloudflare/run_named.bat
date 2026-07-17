@echo off
REM ===== KAASA SmartOS — Cloudflare Named Tunnel 상시 공개 (포트포워딩 불필요) =====
REM 사전(named_tunnel_runbook.md): tunnel login/create/route + config.yml {TUNNEL_ID}{DOMAIN} 치환
REM
REM ★★ 이 PC 에서 실행하면 운영(farmingsight.org)을 가로챈다.
REM   운영은 2026-07-05 iwinv Ubuntu 로 이전됐고 터널 UUID 가 같다. 이 PC 에서 터널이
REM   뜨면 Cloudflare 가 트래픽을 이쪽(개발 코드)으로 보낸다.
REM   2026-07-17 실제 사고: 운영 요청 10/10 이 이 PC 로 갔고 iwinv 배포분이 안 닿았다.
REM   → 오배포 방지로 실행 전 확인을 받는다. 로컬 개발은 터널 없이 localhost:8000 로 충분.
echo.
echo  [경고] 이 스크립트는 farmingsight.org 터널을 이 PC 에 붙입니다.
echo         운영은 iwinv(115.68.226.231) 가 서빙 중이며, 이 PC 가 붙으면 트래픽을
echo         가로채 사용자가 개발 코드를 보게 됩니다.
echo         로컬 개발이 목적이라면 취소하고 http://localhost:8000 을 쓰세요.
echo.
set /p _OK=  정말 진행하려면 YES 를 입력하세요:
if /I not "%_OK%"=="YES" (
  echo  취소했습니다.
  exit /b 1
)
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
