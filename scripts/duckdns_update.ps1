# DuckDNS 동적 IP 갱신 스크립트
# 실행 전 아래 값을 채워주세요
$DUCKDNS_TOKEN  = "여기에_토큰_입력"        # duckdns.org 에서 복사
$DUCKDNS_DOMAIN = "여기에_서브도메인_입력"   # 예: smartfarm-demo

if ($DUCKDNS_TOKEN -eq "여기에_토큰_입력") {
    Write-Host "[!] scripts/duckdns_update.ps1 파일에서 TOKEN과 DOMAIN을 먼저 설정하세요."
    exit 1
}

$url = "https://www.duckdns.org/update?domains=$DUCKDNS_DOMAIN&token=$DUCKDNS_TOKEN&ip="
$result = (Invoke-WebRequest -Uri $url -UseBasicParsing).Content
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "[$timestamp] DuckDNS update: $result"

# 로그 기록
Add-Content -Path "C:\smart_farm\logs\duckdns.log" -Value "[$timestamp] $result"
