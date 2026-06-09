# KAASA SmartOS — DuckDNS IP 자동 갱신 (Windows 작업 스케줄러 5분 주기 권장)
# 사용 전 본인 값으로 치환:
$SUBDOMAIN = "YOUR_SUBDOMAIN"      # 예: kaasafarm  (kaasafarm.duckdns.org)
$TOKEN     = "YOUR_DUCKDNS_TOKEN"  # duckdns.org 로그인 후 발급된 토큰

if ($SUBDOMAIN -eq "YOUR_SUBDOMAIN" -or $TOKEN -eq "YOUR_DUCKDNS_TOKEN") {
    Write-Host "[!] SUBDOMAIN/TOKEN 을 먼저 입력하세요." ; exit 1
}
# 현재 공인 IP는 DuckDNS가 자동 감지(ip 파라미터 비움)
$url = "https://www.duckdns.org/update?domains=$SUBDOMAIN&token=$TOKEN&ip="
try {
    $r = Invoke-RestMethod -Uri $url -TimeoutSec 15
    Write-Host "[DuckDNS] $SUBDOMAIN.duckdns.org → $r"   # 'OK' 면 성공
} catch {
    Write-Host "[DuckDNS] 갱신 실패: $_"
}

# 스케줄 등록(최초 1회, 관리자 PowerShell):
#  $A = New-ScheduledTaskAction -Execute "powershell" -Argument "-File C:\smart_farm\deploy\duckdns\duckdns_update.ps1"
#  $T = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
#  Register-ScheduledTask -TaskName "DuckDNS-KAASA" -Action $A -Trigger $T -RunLevel Highest
