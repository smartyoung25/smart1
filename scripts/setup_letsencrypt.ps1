# Smart Farm — Let's Encrypt 인증서 발급 스크립트 (DuckDNS + certbot)
# 사전 조건:
#   1. DuckDNS 도메인 확정 및 IP 등록 완료
#   2. 공유기 포트 포워딩: 외부 80 → 이 PC 80, 외부 443 → 이 PC 443
#   3. scripts/duckdns_update.ps1 에 TOKEN/DOMAIN 입력 완료
# 실행: powershell -ExecutionPolicy Bypass -File setup_letsencrypt.ps1

param(
    [string]$Domain = "",   # 예: smartfarm-demo.duckdns.org
    [string]$Email  = ""    # 예: you@gmail.com (만료 알림용)
)

if (-not $Domain) {
    # duckdns_update.ps1 에서 도메인 읽기 시도
    $duck = Get-Content "C:\smart_farm\scripts\duckdns_update.ps1" -Raw
    if ($duck -match '\$DUCKDNS_DOMAIN\s*=\s*"([^"]+)"') {
        $sub = $Matches[1]
        if ($sub -ne "여기에_서브도메인_입력") {
            $Domain = "$sub.duckdns.org"
        }
    }
}

if (-not $Domain -or $Domain -eq ".duckdns.org") {
    Write-Host "[ERROR] 도메인이 설정되지 않았습니다."
    Write-Host "        scripts/duckdns_update.ps1 에서 DUCKDNS_DOMAIN을 먼저 설정하세요."
    exit 1
}

Write-Host "도메인: $Domain"
Write-Host ""

# ── 1. winget으로 certbot 설치 ────────────────────────────────────────────────
$certbot = (Get-Command certbot -ErrorAction SilentlyContinue)?.Source
if (-not $certbot) {
    Write-Host "[1/4] certbot 설치 중..."
    winget install EFF.Certbot --accept-package-agreements --accept-source-agreements -h
    # PATH 갱신
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine")
    $certbot = (Get-Command certbot -ErrorAction SilentlyContinue)?.Source
    if (-not $certbot) {
        Write-Host "[ERROR] certbot 설치 실패. https://certbot.eff.org 에서 수동 설치 후 재실행하세요."
        exit 1
    }
} else {
    Write-Host "[1/4] certbot 이미 설치됨: $certbot"
}

# ── 2. nginx 임시 중지 (포트 80 확보) ────────────────────────────────────────
Write-Host "[2/4] nginx 임시 중지..."
cd "C:\nginx"
.\nginx.exe -s stop 2>$null
Start-Sleep -Seconds 2

# ── 3. 인증서 발급 (standalone 모드) ─────────────────────────────────────────
Write-Host "[3/4] 인증서 발급 중: $Domain"
$emailArg = if ($Email) { "--email $Email" } else { "--register-unsafely-without-email" }

certbot certonly --standalone `
    --non-interactive --agree-tos `
    $emailArg.Split(" ") `
    -d $Domain

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] 인증서 발급 실패. 위 오류 메시지를 확인하세요."
    Write-Host "        포트 80이 외부에서 접근 가능한지 확인하세요 (공유기 포트포워딩)."
    # nginx 재시작
    Start-Process -FilePath "C:\nginx\nginx.exe" -ArgumentList "-c conf\nginx.conf" -WindowStyle Hidden
    exit 1
}

$certDir = "C:\Certbot\live\$Domain"
Write-Host "[OK] 인증서 발급 완료: $certDir"

# ── 4. nginx.conf 인증서 경로 교체 ───────────────────────────────────────────
Write-Host "[4/4] nginx.conf 업데이트 중..."
$confPath = "C:\nginx\conf\nginx.conf"
$conf = Get-Content $confPath -Raw -Encoding UTF8

# server_name 업데이트
$conf = $conf -replace 'server_name\s+localhost\s+[\d\.]+;', "server_name $Domain;"

# ssl 인증서 경로 교체 (Let's Encrypt)
$conf = $conf -replace 'ssl_certificate\s+[^\r\n]+;', "ssl_certificate     $certDir/fullchain.pem;"
$conf = $conf -replace 'ssl_certificate_key\s+[^\r\n]+;', "ssl_certificate_key $certDir/privkey.pem;"

$conf | Out-File $confPath -Encoding UTF8
Write-Host "[OK] nginx.conf 업데이트 완료"

# nginx 재시작
Start-Process -FilePath "C:\nginx\nginx.exe" -ArgumentList "-c conf\nginx.conf" -WorkingDirectory "C:\nginx" -WindowStyle Hidden
Start-Sleep -Seconds 2

# ── 5. 자동 갱신 Task Scheduler 등록 ──────────────────────────────────────────
$renewScript = @"
cd C:\nginx; .\nginx.exe -s stop; Start-Sleep 2
certbot renew --quiet --standalone
Start-Process -FilePath 'C:\nginx\nginx.exe' -ArgumentList '-c conf\nginx.conf' -WorkingDirectory 'C:\nginx' -WindowStyle Hidden
"@
$renewScript | Out-File "C:\smart_farm\scripts\renew_cert.ps1" -Encoding UTF8

schtasks /create /tn "SmartFarm-CertRenew" /sc MONTHLY /d 1,15 /st 04:00 `
    /tr "powershell -ExecutionPolicy Bypass -File C:\smart_farm\scripts\renew_cert.ps1" /f | Out-Null

Write-Host ""
Write-Host "======================================================"
Write-Host " Let's Encrypt 설정 완료!"
Write-Host "======================================================"
Write-Host " 도메인 : https://$Domain"
Write-Host " 인증서 : $certDir"
Write-Host " 갱신   : 매월 1일, 15일 04:00 자동 갱신"
Write-Host "======================================================"
Write-Host ""
Write-Host "브라우저에서 확인: https://$Domain"
