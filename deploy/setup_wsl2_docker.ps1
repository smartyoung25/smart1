# setup_wsl2_docker.ps1
# WSL2 + Docker Desktop 설치 및 Smart Farm 스택 기동 스크립트
# 관리자 권한 PowerShell에서 실행:
#   Set-ExecutionPolicy -Scope Process Bypass; .\deploy\setup_wsl2_docker.ps1

param(
    [switch]$SkipWSL,
    [switch]$SkipDocker,
    [switch]$StartOnly
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot

Write-Host "=== Smart Farm AI Platform - WSL2 + Docker 설정 ===" -ForegroundColor Cyan

# ── 1. WSL2 활성화 ────────────────────────────────────────────────────────────
if (-not $SkipWSL -and -not $StartOnly) {
    Write-Host "[1] WSL2 및 가상화 기능 활성화..." -ForegroundColor Yellow

    # Windows 기능 확인
    $wslFeature = Get-WindowsOptionalFeature -Online -FeatureName "Microsoft-Windows-Subsystem-Linux" -ErrorAction SilentlyContinue
    $vmFeature  = Get-WindowsOptionalFeature -Online -FeatureName "VirtualMachinePlatform" -ErrorAction SilentlyContinue

    if ($wslFeature.State -ne "Enabled") {
        Enable-WindowsOptionalFeature -Online -FeatureName "Microsoft-Windows-Subsystem-Linux" -NoRestart
        Write-Host "  WSL 기능 활성화됨 (재시작 필요)" -ForegroundColor Green
    } else {
        Write-Host "  WSL 기능: 이미 활성화" -ForegroundColor Green
    }

    if ($vmFeature.State -ne "Enabled") {
        Enable-WindowsOptionalFeature -Online -FeatureName "VirtualMachinePlatform" -NoRestart
        Write-Host "  VirtualMachinePlatform 활성화됨 (재시작 필요)" -ForegroundColor Green
    } else {
        Write-Host "  VirtualMachinePlatform: 이미 활성화" -ForegroundColor Green
    }

    # WSL 커널 업데이트
    Write-Host "  WSL2 커널 업데이트..." -ForegroundColor Yellow
    try {
        wsl --update 2>&1 | Out-Null
        wsl --set-default-version 2 2>&1 | Out-Null
        Write-Host "  WSL2 커널 최신화 완료" -ForegroundColor Green
    } catch {
        Write-Host "  WARNING: WSL 업데이트 실패 — 재시작 후 재시도" -ForegroundColor Yellow
    }

    # Ubuntu 설치 확인
    $distros = wsl --list --quiet 2>&1
    if ($distros -notmatch "Ubuntu") {
        Write-Host "  Ubuntu 배포판 설치 중..." -ForegroundColor Yellow
        wsl --install -d Ubuntu --no-launch 2>&1 | Out-Null
        Write-Host "  Ubuntu 설치 완료 (첫 실행 시 사용자 설정 필요)" -ForegroundColor Green
    } else {
        Write-Host "  Ubuntu 배포판: 이미 설치됨" -ForegroundColor Green
    }
}

# ── 2. Docker Desktop 설치 ────────────────────────────────────────────────────
if (-not $SkipDocker -and -not $StartOnly) {
    $dockerPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $dockerPath)) {
        Write-Host "[2] Docker Desktop 설치 중 (winget)..." -ForegroundColor Yellow
        winget install Docker.DockerDesktop --silent --accept-package-agreements --accept-source-agreements
        Write-Host "  Docker Desktop 설치 완료" -ForegroundColor Green
    } else {
        Write-Host "[2] Docker Desktop: 이미 설치됨" -ForegroundColor Green
    }
}

# ── 3. Docker Desktop 시작 ────────────────────────────────────────────────────
Write-Host "[3] Docker Desktop 시작..." -ForegroundColor Yellow
$dockerExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
if (Test-Path $dockerExe) {
    Start-Process -FilePath $dockerExe -WindowStyle Hidden

    Write-Host "  Docker Desktop 기동 대기 (최대 90초)..." -ForegroundColor Yellow
    $timeout = 90
    $waited  = 0
    while ($waited -lt $timeout) {
        Start-Sleep -Seconds 5
        $waited += 5
        try {
            $null = & docker info 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  Docker 준비 완료 ($waited 초)" -ForegroundColor Green
                break
            }
        } catch {}
        Write-Host "  대기 중... ($waited/$timeout 초)"
    }

    if ($waited -ge $timeout) {
        Write-Host "  [WARNING] Docker Desktop이 $timeout 초 내에 응답하지 않음" -ForegroundColor Yellow
        Write-Host "  Docker Desktop 트레이 아이콘을 확인하거나 수동으로 재시작하세요." -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "  [ERROR] Docker Desktop 실행 파일 없음: $dockerExe" -ForegroundColor Red
    exit 1
}

# ── 4. docker-compose.override.yml db scale 설정 확인 ────────────────────────
$overridePath = "$ProjectDir\docker-compose.override.yml"
if (Test-Path $overridePath) {
    $override = Get-Content $overridePath -Raw
    if ($override -match "profiles:.*docker-db-only") {
        Write-Host "[4] override.yml 호환성 수정 (profiles → replicas: 0)..." -ForegroundColor Yellow
        $override = $override -replace "profiles:\s*\n\s*- docker-db-only", "deploy:`n      replicas: 0"
        Set-Content -Path $overridePath -Value $override -Encoding utf8
        Write-Host "  override.yml 갱신 완료" -ForegroundColor Green
    } else {
        Write-Host "[4] override.yml: OK" -ForegroundColor Green
    }
}

# ── 5. Docker 이미지 빌드 및 서비스 시작 ────────────────────────────────────
Write-Host "[5] Smart Farm 스택 시작..." -ForegroundColor Yellow
Set-Location $ProjectDir

& docker compose build --no-cache api pipeline 2>&1 | Select-Object -Last 5
& docker compose up -d 2>&1 | Select-Object -Last 10

Start-Sleep -Seconds 15

# ── 6. 헬스체크 ──────────────────────────────────────────────────────────────
Write-Host "[6] 헬스체크..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 10 -UseBasicParsing
    if ($response.StatusCode -eq 200) {
        Write-Host "  API 헬스체크 PASS: $($response.Content)" -ForegroundColor Green
    }
} catch {
    Write-Host "  [WARN] 헬스체크 실패 — 서비스 기동 시간이 더 필요할 수 있습니다." -ForegroundColor Yellow
    Write-Host "         30초 후 http://localhost 접속 시도" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== 설정 완료 ===" -ForegroundColor Cyan
Write-Host "  대시보드: http://localhost"
Write-Host "  API:      http://localhost:8000/docs"
Write-Host "  로그:     docker compose logs -f api"
