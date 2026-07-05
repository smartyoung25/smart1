# cloudflared 터널 + watchdog 정지 (관리자 권한 필요). 결과는 stop_result.txt 로 기록.
$log = "C:\smart_farm\deploy\cloudflare\stop_result.txt"
Set-Content -Path $log -Value ("START " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss")) -Encoding utf8

# 1) 예약작업 비활성(재기동 차단) + 중지
try {
    Disable-ScheduledTask -TaskName "SmartFarm-Watchdog" -ErrorAction Stop | Out-Null
    Add-Content $log "task_disabled=OK"
} catch {
    Add-Content $log ("task_disable_FAIL=" + $_.Exception.Message)
}
try { Stop-ScheduledTask -TaskName "SmartFarm-Watchdog" -ErrorAction SilentlyContinue } catch {}

# 2) watchdog.ps1 프로세스 종료
$wd = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*watchdog.ps1*" }
foreach ($p in $wd) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Add-Content $log ("watchdog_killed=" + $p.ProcessId)
}

# 3) cloudflared 종료
Start-Sleep -Seconds 1
$cf = Get-Process cloudflared -ErrorAction SilentlyContinue
foreach ($p in $cf) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Add-Content $log ("cloudflared_killed=" + $p.Id)
}
Start-Sleep -Seconds 2

# 4) 결과 확인
$cf2 = @(Get-Process cloudflared -ErrorAction SilentlyContinue)
Add-Content $log ("cloudflared_remaining=" + $cf2.Count)
$state = try { (Get-ScheduledTask -TaskName "SmartFarm-Watchdog").State } catch { "NA" }
Add-Content $log ("task_state=" + $state)
Add-Content $log "DONE"
