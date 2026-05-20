@echo off
REM Smart Farm AI Platform — 서비스 시작 스크립트 (Windows)
REM 사용: start_services.bat

setlocal
set SMART_FARM=C:\smart_farm
set PGSQL=C:\PostgreSQL\pgsql
set NGINX=C:\nginx
set PYTHON=C:\tools\python311\python.exe

echo [Smart Farm] 서비스 시작 중...

REM ── 1. PostgreSQL ──────────────────────────────────────────────────────────
echo [1/4] PostgreSQL 시작...
%PGSQL%\bin\pg_ctl status -D %PGSQL%\data > nul 2>&1
if errorlevel 1 (
    %PGSQL%\bin\pg_ctl start -D %PGSQL%\data -l %PGSQL%\data\postgres.log
    timeout /t 3 /nobreak > nul
) else (
    echo       이미 실행 중
)

REM ── 2. FastAPI (uvicorn) ───────────────────────────────────────────────────
echo [2/4] FastAPI 시작...
tasklist /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq smartfarm-api*" 2>nul | find "python.exe" > nul
if errorlevel 1 (
    cd /d %SMART_FARM%
    start "smartfarm-api" /MIN %PYTHON% -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level info
    timeout /t 3 /nobreak > nul
) else (
    echo       이미 실행 중
)

REM ── 3. nginx ──────────────────────────────────────────────────────────────
echo [3/4] nginx 시작...
tasklist /FI "IMAGENAME eq nginx.exe" 2>nul | find "nginx.exe" > nul
if errorlevel 1 (
    cd /d %NGINX%
    start "" /B nginx.exe -c conf\nginx.conf
    timeout /t 2 /nobreak > nul
) else (
    echo       이미 실행 중
)

REM ── 4. MQTT Subscriber (선택적) ──────────────────────────────────────────
REM echo [4/4] MQTT Subscriber 시작...
REM cd /d %SMART_FARM%
REM start "smartfarm-mqtt" /MIN %PYTHON% -m pipeline.mqtt_subscriber

echo.
echo [Smart Farm] 서비스 시작 완료
echo   대시보드:  http://localhost/
echo   API 문서:  http://localhost/docs
echo   API 직접:  http://localhost:8000/health
echo.
