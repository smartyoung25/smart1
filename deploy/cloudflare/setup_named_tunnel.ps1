# ===== KAASA SmartOS — Cloudflare Named Tunnel 턴키 설정 =====
# 사용자 작업: ① Cloudflare 계정 + 도메인 등록(네임서버 Cloudflare로) ② 아래 1회 실행
#   powershell -ExecutionPolicy Bypass -File deploy\cloudflare\setup_named_tunnel.ps1 -Domain app.your-domain.com
# 스크립트가 자동 처리: login → create → Tunnel ID 파싱 → DNS 라우팅 → config.yml 생성
# (브라우저 로그인 창은 사용자가 1회 승인. 그 외 전부 자동)
param(
    [Parameter(Mandatory = $true)][string]$Domain,
    [string]$TunnelName = "kaasa-smartos",
    [switch]$Run   # 설정 후 바로 실행하려면 -Run
)
$ErrorActionPreference = "Stop"
$ROOT = "C:\smart_farm"
$CF   = "$ROOT\deploy\cloudflare\bin\cloudflared.exe"
$CFG  = "$ROOT\deploy\cloudflare\config.yml"
if (-not (Test-Path $CF)) { Write-Error "cloudflared 없음: $CF"; exit 1 }

Write-Host "[1/5] Cloudflare 로그인 (브라우저에서 도메인 선택·승인)" -ForegroundColor Cyan
& $CF tunnel login
if ($LASTEXITCODE -ne 0) { Write-Error "로그인 실패"; exit 1 }

Write-Host "[2/5] 터널 생성: $TunnelName" -ForegroundColor Cyan
# 이미 있으면 재사용, 없으면 생성
$existing = (& $CF tunnel list 2>$null | Select-String $TunnelName)
if (-not $existing) { & $CF tunnel create $TunnelName }

Write-Host "[3/5] Tunnel ID 조회" -ForegroundColor Cyan
$line = (& $CF tunnel list 2>$null | Select-String $TunnelName | Select-Object -First 1).ToString()
$TunnelId = ($line -split '\s+')[0]
if (-not $TunnelId) { Write-Error "Tunnel ID 파싱 실패 — 'cloudflared tunnel list' 확인"; exit 1 }
Write-Host "    Tunnel ID = $TunnelId"
$cred = "$env:USERPROFILE\.cloudflared\$TunnelId.json"

Write-Host "[4/5] DNS 라우팅: $Domain → $TunnelName" -ForegroundColor Cyan
& $CF tunnel route dns $TunnelName $Domain

Write-Host "[5/5] config.yml 생성" -ForegroundColor Cyan
@"
# Cloudflare Named Tunnel — KAASA SmartOS (자동 생성)
tunnel: $TunnelId
credentials-file: $cred
ingress:
  - hostname: $Domain
    service: http://localhost:8000
  - service: http_status:404
"@ | Out-File -FilePath $CFG -Encoding utf8

Write-Host ""
Write-Host "✅ 설정 완료. 공개 주소: https://$Domain/intro" -ForegroundColor Green
Write-Host "   상시 실행:  deploy\cloudflare\run_named.bat   (API+터널, PUBLIC_DEMO 읽기전용)" -ForegroundColor Yellow
Write-Host "   부팅 자동:  `"$CF`" service install" -ForegroundColor Yellow

if ($Run) {
    Write-Host "`n[옵션] 지금 실행 (-Run)" -ForegroundColor Cyan
    Start-Process "$ROOT\deploy\cloudflare\run_named.bat"
}
