# enable_wsl2_admin.ps1
# WSL2 활성화 스크립트 (관리자 권한 필요)
#
# 실행 방법:
#   1. 시작 메뉴 → "Windows PowerShell" → 우클릭 → "관리자 권한으로 실행"
#   2. 아래 명령 실행:
#      Set-ExecutionPolicy -Scope Process Bypass
#      C:\smart_farm\deploy\enable_wsl2_admin.ps1
#
# 완료 후 재부팅하면 WSL2 + Docker Desktop이 자동으로 정상 기동됩니다.

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

Write-Host "=== WSL2 활성화 ===" -ForegroundColor Cyan

# 1. Windows 기능 활성화
$wslState = (Get-WindowsOptionalFeature -Online -FeatureName "Microsoft-Windows-Subsystem-Linux").State
$vmState  = (Get-WindowsOptionalFeature -Online -FeatureName "VirtualMachinePlatform").State

if ($wslState -ne "Enabled") {
    Write-Host "[1] WSL 기능 활성화 중..." -ForegroundColor Yellow
    Enable-WindowsOptionalFeature -Online -FeatureName "Microsoft-Windows-Subsystem-Linux" -NoRestart
    Write-Host "    완료 (재부팅 필요)" -ForegroundColor Green
} else {
    Write-Host "[1] WSL 기능: 이미 활성화" -ForegroundColor Green
}

if ($vmState -ne "Enabled") {
    Write-Host "[2] VirtualMachinePlatform 활성화 중..." -ForegroundColor Yellow
    Enable-WindowsOptionalFeature -Online -FeatureName "VirtualMachinePlatform" -NoRestart
    Write-Host "    완료 (재부팅 필요)" -ForegroundColor Green
} else {
    Write-Host "[2] VirtualMachinePlatform: 이미 활성화" -ForegroundColor Green
}

# 2. WSL2 기본 버전 설정
Write-Host "[3] WSL2 기본 버전 설정..." -ForegroundColor Yellow
try {
    wsl --set-default-version 2 2>&1 | Out-Null
    Write-Host "    WSL2 기본 버전 설정 완료" -ForegroundColor Green
} catch {
    Write-Host "    WSL2 설정은 재부팅 후 자동 적용됩니다" -ForegroundColor Yellow
}

# 3. Ubuntu 배포판 예약 설치 (재부팅 후 자동)
$distros = wsl --list --quiet 2>&1
if ($distros -notmatch "Ubuntu") {
    Write-Host "[4] Ubuntu 배포판 설치 예약..." -ForegroundColor Yellow
    wsl --install -d Ubuntu --no-launch 2>&1 | Out-Null
    Write-Host "    Ubuntu 설치 예약 완료" -ForegroundColor Green
} else {
    Write-Host "[4] Ubuntu: 이미 설치됨" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 준비 완료 — 지금 재부팅하세요 ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "재부팅 후 실행 순서:"
Write-Host "  1. Docker Desktop 트레이 아이콘이 초록색인지 확인"
Write-Host "  2. PowerShell에서 실행:"
Write-Host "     cd C:\smart_farm"
Write-Host "     docker compose up -d"
Write-Host "     python -m pipelines.initial_load"
Write-Host ""

$reboot = Read-Host "지금 재부팅하시겠습니까? (y/N)"
if ($reboot -eq 'y' -or $reboot -eq 'Y') {
    Write-Host "30초 후 재부팅..." -ForegroundColor Yellow
    shutdown /r /t 30 /c "Smart Farm WSL2 활성화를 위한 재부팅"
}
