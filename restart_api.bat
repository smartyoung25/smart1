@echo off
REM Smart Farm AI — FastAPI 재시작 스크립트
REM 포트 8000을 점유한 python 프로세스 종료 후 재시작

setlocal
set SMART_FARM=C:\smart_farm
set PYTHON=python

echo [Smart Farm] FastAPI 재시작...

REM 포트 8000 점유 PID 조회 후 종료
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000 " ^| find "LISTENING"') do (
    echo   PID %%a 종료 중...
    taskkill /PID %%a /F > nul 2>&1
)
timeout /t 2 /nobreak > nul

REM 재시작
cd /d %SMART_FARM%
set PYTHONPATH=%SMART_FARM%
start "smartfarm-api" /MIN %PYTHON% -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level warning
timeout /t 4 /nobreak > nul

REM 헬스체크
curl -sf http://localhost:8000/health > nul 2>&1
if errorlevel 1 (
    echo [ERROR] 서버 응답 없음. 로그 확인 필요.
) else (
    echo [OK] FastAPI 재시작 완료 — http://localhost:8000/health
)
endlocal
