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

REM ── 4. mosquitto MQTT 브로커 ─────────────────────────────────────────────
echo [4/5] mosquitto (MQTT) 시작...
tasklist /FI "IMAGENAME eq mosquitto.exe" 2>nul | find "mosquitto.exe" > nul
if errorlevel 1 (
    start "" /B "C:\Program Files\mosquitto\mosquitto.exe" -c "C:\smart_farm\mosquitto\config\mosquitto-windows.conf"
    timeout /t 2 /nobreak > nul
    echo       포트 1883 (MQTT), 9001 (WebSocket)
) else (
    echo       이미 실행 중
)

REM ── 5. MQTT Subscriber ───────────────────────────────────────────────────
echo [5/5] MQTT Subscriber 시작...
tasklist /FI "WINDOWTITLE eq smartfarm-mqtt*" 2>nul | find "python.exe" > nul
if errorlevel 1 (
    cd /d %SMART_FARM%
    start "smartfarm-mqtt" /MIN %PYTHON% pipeline\mqtt_subscriber.py
    timeout /t 2 /nobreak > nul
    echo       smartfarm/+/env, smartfarm/+/prod 구독 시작
) else (
    echo       이미 실행 중
)

echo.
echo [Smart Farm] 서비스 시작 완료
echo   대시보드:  http://localhost/
echo   API 문서:  http://localhost/docs
echo   API 직접:  http://localhost:8000/health
echo   MQTT:      localhost:1883
echo   MQTT-WS:   ws://localhost:9001
echo.
