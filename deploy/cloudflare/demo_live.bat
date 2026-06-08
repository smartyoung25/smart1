@echo off
REM ===== KAASA SmartOS — 임시 공개 데모(읽기전용 + Cloudflare 퀵터널) =====
REM 보안: PUBLIC_DEMO=1(쓰기·관리자 차단) + 강력 JWT_SECRET(.env)
set SMART_FARM=C:\smart_farm
set PYTHON=C:\tools\python311\python.exe
set CLOUDFLARED=C:\Users\IIamHub3\AppData\Local\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe
set PYTHONPATH=%SMART_FARM%
set PYTHONIOENCODING=utf-8
set PUBLIC_DEMO=1
cd /d %SMART_FARM%
REM 1) 읽기전용 모드로 API 기동
start "kaasa-demo-api" /MIN %PYTHON% -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level warning
timeout /t 6 /nobreak >/dev/null
REM 2) 퀵 터널 (공개 URL은 콘솔에 출력됨, 종료=이 창 닫기)
echo 공개 URL이 아래에 표시됩니다. 시연 종료 시 이 창을 닫으세요.
"%CLOUDFLARED%" tunnel --url http://localhost:8000 --no-autoupdate
