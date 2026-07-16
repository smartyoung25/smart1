# ============================================================
#  SmartFarm-Watchdog 예약작업 등록 (★ 관리자 PowerShell에서 1회 실행)
#  목적: 재부팅/watchdog 사망 시에도 uvicorn(8000)+터널이 자동 복구되도록
#        watchdog.ps1 을 '로그온 시 + 15분 주기'로 자동 시작.
#  실행: 관리자 권한 PowerShell에서
#        powershell -ExecutionPolicy Bypass -File deploy\cloudflare\register_watchdog_task.ps1
#  해제: Unregister-ScheduledTask -TaskName 'SmartFarm-Watchdog' -Confirm:$false
# ============================================================
$ErrorActionPreference = "Stop"

$taskName = "SmartFarm-Watchdog"
$wd       = "C:\smart_farm\deploy\cloudflare\watchdog.ps1"

if (-not (Test-Path $wd)) { Write-Host "watchdog.ps1 없음: $wd"; exit 1 }

# 기존 동명 작업 제거(멱등)
try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop; Write-Host "기존 $taskName 제거" } catch {}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -NonInteractive -File `"$wd`""

# 로그온 시 기동(재부팅 대비) + 15분 주기 재시도(watchdog 사망 대비 — 살아있으면 단일인스턴스 가드가 즉시 종료)
$trigLogon  = New-ScheduledTaskTrigger -AtLogOn
$trigRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)   # RepetitionDuration 생략 = 무기한

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($trigLogon, $trigRepeat) `
    -Settings $settings -RunLevel Highest `
    -Description "KAASA Farmingsight watchdog 자동시작(로그온+15분). uvicorn8000/cloudflared 자동복구." -Force | Out-Null

Write-Host "=== 등록 완료 ==="
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State | Format-Table -Auto
Write-Host "지금 즉시 1회 시작하려면: Start-ScheduledTask -TaskName '$taskName'"
