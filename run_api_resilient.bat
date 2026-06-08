@echo off
REM ============================================================
REM  Smart Farm API — 자동 재기동 래퍼 (로컬 dev/시연용)
REM  uvicorn 이 어떤 이유로 종료돼도 자동 재시작 → 데모 중 다운 방지.
REM  (도커 운영 경로는 docker-compose restart:unless-stopped 로 이미 보장)
REM  중지: 이 창을 닫거나 Ctrl+C 두 번.
REM ============================================================
setlocal
set SMART_FARM=C:\smart_farm
set PYTHON=C:\tools\python311\python.exe
set PYTHONPATH=%SMART_FARM%
set PYTHONIOENCODING=utf-8
cd /d %SMART_FARM%

REM 포트 8000 기존 점유 프로세스 정리
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000 " ^| find "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
timeout /t 1 /nobreak >nul

:loop
echo [%date% %time%] API 시작 (http://localhost:8000/intro)
%PYTHON% -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level warning
echo [%date% %time%] !! API 종료(code %errorlevel%) — 3초 후 자동 재시작 !!
timeout /t 3 /nobreak >nul
goto loop
