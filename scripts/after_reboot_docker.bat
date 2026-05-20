@echo off
REM Smart Farm — WSL2 재부팅 후 Docker 컨테이너 시작 스크립트
REM WSL2 설치 + 재부팅 완료 후 이 파일을 실행하세요.

echo [Smart Farm] Docker 컨테이너 시작 중...
echo.

REM Docker Desktop 실행 대기
set WAIT=0
:WAIT_DOCKER
docker info > nul 2>&1
if errorlevel 1 (
    set /a WAIT+=1
    if %WAIT% GEQ 30 (
        echo [ERROR] Docker가 30초 내에 응답하지 않습니다.
        echo         Docker Desktop을 수동으로 시작한 후 다시 실행하세요.
        pause
        exit /b 1
    )
    echo [%WAIT%/30] Docker 응답 대기 중...
    timeout /t 1 /nobreak > nul
    goto WAIT_DOCKER
)

echo [OK] Docker 응답 확인
echo.

REM docker compose 실행 (로컬 PostgreSQL 사용 override)
cd /d C:\smart_farm
docker compose -f docker-compose.override.yml up -d api pipeline

echo.
echo [OK] 컨테이너 시작 완료
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo.
echo 대시보드: http://localhost/
echo API 문서: http://localhost/docs
pause
