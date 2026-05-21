# after_wsl2_reboot.ps1
# WSL2 재부팅 완료 후 Docker + Smart Farm 스택 전체 기동
#
# 실행 방법: (일반 사용자 PowerShell로 실행 가능)
#   cd C:\smart_farm
#   .\deploy\after_wsl2_reboot.ps1
#
# 또는 관리자 PowerShell:
#   Set-ExecutionPolicy -Scope Process Bypass
#   C:\smart_farm\deploy\after_wsl2_reboot.ps1

$ErrorActionPreference = "Stop"
$ProjectDir = "C:\smart_farm"
Set-Location $ProjectDir

Write-Host "=== Smart Farm — WSL2 재부팅 후 전체 기동 ===" -ForegroundColor Cyan

# ── 1. WSL2 확인 ──────────────────────────────────────────────────────────────
Write-Host "[1] WSL2 상태 확인..." -ForegroundColor Yellow
try {
    $wslVer = (wsl --version 2>&1 | Select-String "WSL 버전|WSL version" | Select-Object -First 1).ToString()
    Write-Host "    $wslVer" -ForegroundColor Green
} catch {
    Write-Host "    [WARN] WSL2 응답 없음 — Docker가 시작되면 자동 활성화됩니다" -ForegroundColor Yellow
}

# ── 2. Docker Desktop 기동 ────────────────────────────────────────────────────
Write-Host "[2] Docker Desktop 기동..." -ForegroundColor Yellow
$dockerExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
if (-not (Test-Path $dockerExe)) {
    Write-Host "    [ERROR] Docker Desktop 없음: $dockerExe" -ForegroundColor Red
    exit 1
}

$running = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
if (-not $running) {
    Start-Process -FilePath $dockerExe -WindowStyle Minimized
    Write-Host "    Docker Desktop 시작됨, 최대 90초 대기..." -ForegroundColor Yellow
}

# Docker 엔진 응답 대기
$waited = 0; $ready = $false
while ($waited -lt 90) {
    Start-Sleep -Seconds 5; $waited += 5
    try {
        $null = docker info 2>&1
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    } catch {}
    Write-Host "    대기 중... ($waited/90초)"
}

if (-not $ready) {
    Write-Host "    [WARN] Docker가 90초 내 응답하지 않음. 트레이 아이콘 확인 후 재시도하세요." -ForegroundColor Yellow
    exit 1
}
Write-Host "    Docker 준비 완료 ($waited초)" -ForegroundColor Green

# ── 3. Docker 이미지 빌드 ─────────────────────────────────────────────────────
Write-Host "[3] Docker 이미지 빌드..." -ForegroundColor Yellow
& docker compose build --no-cache api pipeline 2>&1 | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) {
    Write-Host "    [ERROR] 빌드 실패" -ForegroundColor Red; exit 1
}
Write-Host "    빌드 완료" -ForegroundColor Green

# ── 4. 스택 기동 (override.yml 적용 — 로컬 PG 사용) ──────────────────────────
Write-Host "[4] Docker Compose 스택 기동..." -ForegroundColor Yellow
& docker compose up -d 2>&1 | Select-Object -Last 10
if ($LASTEXITCODE -ne 0) {
    Write-Host "    [ERROR] docker compose up 실패" -ForegroundColor Red; exit 1
}
Write-Host "    스택 기동 완료" -ForegroundColor Green

# ── 5. 헬스체크 대기 ─────────────────────────────────────────────────────────
Write-Host "[5] API 헬스체크 (최대 60초)..." -ForegroundColor Yellow
$waited = 0; $apiReady = $false
while ($waited -lt 60) {
    Start-Sleep -Seconds 5; $waited += 5
    try {
        $r = Invoke-WebRequest "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $apiReady = $true; break }
    } catch {}
    Write-Host "    대기 중... ($waited/60초)"
}

if ($apiReady) {
    Write-Host "    API 헬스체크 PASS" -ForegroundColor Green
} else {
    Write-Host "    [WARN] API 응답 지연. 로그 확인: docker compose logs -f api" -ForegroundColor Yellow
}

# ── 6. nginx 통해 대시보드 확인 ───────────────────────────────────────────────
try {
    $dash = Invoke-WebRequest "http://localhost" -UseBasicParsing -TimeoutSec 5
    Write-Host "[6] 대시보드 응답: HTTP $($dash.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "[6] 대시보드 응답 없음 (nginx 시작 지연일 수 있음)" -ForegroundColor Yellow
}

# ── 7. 완료 ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== 기동 완료 ===" -ForegroundColor Cyan
Write-Host "  대시보드: http://localhost"
Write-Host "  API Docs: http://localhost:8000/docs"
Write-Host "  로그:     docker compose logs -f api"
Write-Host ""
Write-Host "컨테이너 상태:"
& docker compose ps
