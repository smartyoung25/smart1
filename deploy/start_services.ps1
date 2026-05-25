# ─────────────────────────────────────────────────────────────────────────────
# Smart Farm AI Platform — 서비스 시작 스크립트
# 사용법: PowerShell에서 실행 (관리자 권한 불필요)
#   cd C:\smart_farm
#   .\deploy\start_services.ps1
#
# 시작 순서: nginx → uvicorn (FastAPI)
# 접속 URL:
#   대시보드: http://localhost/       (nginx :80)
#   API 직접: http://localhost:8000/  (uvicorn 직접)
# ─────────────────────────────────────────────────────────────────────────────

$PROJECT_ROOT = "C:\smart_farm"
$NGINX_DIR    = "C:\nginx"
$NGINX_EXE    = "$NGINX_DIR\nginx.exe"

Set-Location $PROJECT_ROOT

# ── 1. nginx 시작 ──────────────────────────────────────────────────────────
Write-Host "[1/2] nginx 시작 중..." -ForegroundColor Cyan

$nginxRunning = Get-Process nginx -ErrorAction SilentlyContinue
if ($nginxRunning) {
    Write-Host "  nginx 이미 실행 중 (PID: $($nginxRunning.Id))" -ForegroundColor Yellow
} elseif (Test-Path $NGINX_EXE) {
    Start-Process -FilePath $NGINX_EXE -WorkingDirectory $NGINX_DIR -WindowStyle Hidden
    Start-Sleep -Seconds 1
    $port80 = netstat -ano | Select-String ":80 " | Select-String "LISTENING"
    if ($port80) {
        Write-Host "  nginx 시작 완료 — 포트 80 리스닝" -ForegroundColor Green
    } else {
        Write-Host "  nginx 시작했으나 포트 80 확인 실패 — 로그 확인: $NGINX_DIR\logs\error.log" -ForegroundColor Red
    }
} else {
    Write-Host "  nginx.exe 없음: $NGINX_EXE" -ForegroundColor Red
    Write-Host "  nginx 설치 필요: https://nginx.org/en/download.html → C:\nginx" -ForegroundColor Yellow
}

# ── 2. FastAPI (uvicorn) 시작 ──────────────────────────────────────────────
Write-Host "[2/2] FastAPI (uvicorn) 시작 중..." -ForegroundColor Cyan

$port8000 = netstat -ano | Select-String ":8000 " | Select-String "LISTENING"
if ($port8000) {
    Write-Host "  uvicorn 이미 실행 중 (포트 8000)" -ForegroundColor Yellow
} else {
    # 백그라운드로 uvicorn 시작
    Start-Process -FilePath "python" `
        -ArgumentList "-m uvicorn api.main:app --host 0.0.0.0 --port 8000" `
        -WorkingDirectory $PROJECT_ROOT `
        -WindowStyle Minimized

    # 최대 10초 대기
    $waited = 0
    do {
        Start-Sleep -Seconds 1
        $waited++
        $up = netstat -ano | Select-String ":8000 " | Select-String "LISTENING"
    } while (-not $up -and $waited -lt 10)

    if ($up) {
        Write-Host "  uvicorn 시작 완료 — 포트 8000 리스닝 ($waited초 소요)" -ForegroundColor Green
    } else {
        Write-Host "  uvicorn 시작 실패 또는 타임아웃. 수동 실행:" -ForegroundColor Red
        Write-Host "  python -m uvicorn api.main:app --host 0.0.0.0 --port 8000" -ForegroundColor Gray
    }
}

# ── 상태 요약 ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host " 접속 URL" -ForegroundColor White
Write-Host "  대시보드 (nginx):  http://localhost/"         -ForegroundColor Green
Write-Host "  API 직접 접근:     http://localhost:8000/"    -ForegroundColor Green
Write-Host "  API 문서 (Swagger): http://localhost/docs"    -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
