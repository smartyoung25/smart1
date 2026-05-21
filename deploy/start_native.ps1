# start_native.ps1
# Docker 없이 로컬 PostgreSQL + Python으로 Smart Farm API 기동
# 사용: PowerShell에서 .\deploy\start_native.ps1
# 옵션:
#   -Port 8000        API 포트 (기본 8000)
#   -Workers 1        uvicorn worker 수 (기본 1)
#   -Reload           개발 모드 (자동 리로드)

param(
    [int]   $Port    = 8000,
    [int]   $Workers = 1,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot

Set-Location $ProjectDir

Write-Host "=== Smart Farm AI Platform — 네이티브 시작 ===" -ForegroundColor Cyan

# ── 1. 환경변수 로드 ──────────────────────────────────────────────────────────
$envFile = "$ProjectDir\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.+)$') {
            $key = $Matches[1].Trim()
            $val = $Matches[2].Trim().Trim('"').Trim("'")
            [System.Environment]::SetEnvironmentVariable($key, $val, 'Process')
        }
    }
    Write-Host "[1] .env 로드 완료" -ForegroundColor Green
} else {
    Write-Host "[1] .env 없음 — 기본값 사용" -ForegroundColor Yellow
}

# ── 2. PostgreSQL 연결 확인 ───────────────────────────────────────────────────
$pgReady = $false
try {
    $pgBin = "C:\Program Files\PostgreSQL\17\bin\pg_isready.exe"
    if (Test-Path $pgBin) {
        $result = & $pgBin -h 127.0.0.1 -p 5432 2>&1
        $pgReady = ($LASTEXITCODE -eq 0)
    }
} catch {}

if ($pgReady) {
    Write-Host "[2] PostgreSQL 연결 확인 OK" -ForegroundColor Green
} else {
    Write-Host "[2] PostgreSQL 미연결 — in-memory 모드로 기동" -ForegroundColor Yellow
    $env:DATABASE_URL = ""
}

# ── 3. Python 경로 확인 ───────────────────────────────────────────────────────
$pythonExe = "C:\tools\python311\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $pythonExe) {
    Write-Host "[ERROR] Python을 찾을 수 없습니다." -ForegroundColor Red
    exit 1
}
Write-Host "[3] Python: $pythonExe" -ForegroundColor Green

# ── 4. uvicorn 기동 ──────────────────────────────────────────────────────────
Write-Host "[4] API 서버 기동 (포트 $Port)..." -ForegroundColor Yellow

$uvArgs = @(
    "-m", "uvicorn",
    "api.main:app",
    "--host", "0.0.0.0",
    "--port", "$Port",
    "--workers", "$Workers"
)
if ($Reload) { $uvArgs += "--reload" }

Write-Host "    명령: $pythonExe $($uvArgs -join ' ')" -ForegroundColor Gray
Write-Host ""
Write-Host "  대시보드: http://localhost:$Port"
Write-Host "  API Docs: http://localhost:$Port/docs"
Write-Host ""

& $pythonExe @uvArgs
