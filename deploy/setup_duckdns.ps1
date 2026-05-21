# setup_duckdns.ps1
# DuckDNS 동적 DNS 설정 및 자동 업데이트 예약 작업 등록
#
# 사전 준비:
#   1. https://www.duckdns.org 에서 도메인 생성 (예: myfarm.duckdns.org)
#   2. 토큰 복사
#   3. 관리자 PowerShell에서 실행:
#      .\deploy\setup_duckdns.ps1 -Domain myfarm -Token <your-token>

param(
    [Parameter(Mandatory=$true)]
    [string]$Domain,

    [Parameter(Mandatory=$true)]
    [string]$Token,

    [int]$IntervalMinutes = 5,
    [switch]$TestOnly
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$ScriptPath = "$ProjectDir\deploy\duckdns_update.ps1"

Write-Host "=== DuckDNS 설정 ===" -ForegroundColor Cyan
Write-Host "  도메인: $Domain.duckdns.org"
Write-Host "  갱신주기: $IntervalMinutes 분마다"

# ── 1. 업데이트 스크립트 생성 ─────────────────────────────────────────────────
@"
# duckdns_update.ps1 — 자동 생성됨 (setup_duckdns.ps1)
`$domain = "$Domain"
`$token  = "$Token"
`$url    = "https://www.duckdns.org/update?domains=`$domain&token=`$token&ip="
try {
    `$resp = Invoke-WebRequest -Uri `$url -UseBasicParsing -TimeoutSec 10
    `$ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path "$ProjectDir\deploy\duckdns.log" -Value "`$ts `$(`$resp.Content)"
} catch {
    Add-Content -Path "$ProjectDir\deploy\duckdns.log" -Value "`$(Get-Date) ERROR: `$_"
}
"@ | Set-Content -Path $ScriptPath -Encoding utf8

Write-Host "[1] 업데이트 스크립트 생성: $ScriptPath" -ForegroundColor Green

# ── 2. 즉시 테스트 ───────────────────────────────────────────────────────────
Write-Host "[2] DuckDNS 즉시 업데이트 테스트..." -ForegroundColor Yellow
$testUrl = "https://www.duckdns.org/update?domains=$Domain&token=$Token&ip="
try {
    $resp = Invoke-WebRequest -Uri $testUrl -UseBasicParsing -TimeoutSec 10
    $result = $resp.Content.Trim()
    if ($result -eq "OK") {
        Write-Host "  테스트 결과: OK — IP 등록 성공" -ForegroundColor Green
    } else {
        Write-Host "  테스트 결과: $result" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  테스트 실패: $_" -ForegroundColor Red
    exit 1
}

if ($TestOnly) { exit 0 }

# ── 3. 예약 작업 등록 ─────────────────────────────────────────────────────────
Write-Host "[3] Windows 예약 작업 등록 (${IntervalMinutes}분마다)..." -ForegroundColor Yellow

$taskName = "SmartFarm-DuckDNS"
$action   = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$ScriptPath`""
$trigger  = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -Once -At (Get-Date)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# 기존 작업 제거 후 재등록
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Description "Smart Farm DuckDNS IP 갱신" | Out-Null

Write-Host "  예약 작업 등록 완료: $taskName" -ForegroundColor Green

# ── 4. 완료 ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== DuckDNS 설정 완료 ===" -ForegroundColor Cyan
Write-Host "  외부 접속 URL: https://$Domain.duckdns.org"
Write-Host "  로그: $ProjectDir\deploy\duckdns.log"
Write-Host ""
Write-Host "다음 단계: HTTPS 인증서 발급"
Write-Host "  .\deploy\setup_https.sh $Domain.duckdns.org  (WSL2 환경에서)"
Write-Host "  또는 .\deploy\gen_selfsigned_cert.sh  (자체 서명, 개발용)"
