# Smart Farm — Windows 작업 스케줄러 등록 스크립트
# 관리자 권한으로 실행: powershell -ExecutionPolicy Bypass -File setup_task_scheduler.ps1

$PYTHON  = "C:\tools\python311\python.exe"
$APPDIR  = "C:\smart_farm"
$LOGDIR  = "C:\smart_farm\logs"

if (!(Test-Path $LOGDIR)) { New-Item -ItemType Directory -Force $LOGDIR | Out-Null }

# ── 1. PostgreSQL 자동 시작 (부팅 시) ────────────────────────────────────
$pgAction = New-ScheduledTaskAction `
    -Execute "C:\PostgreSQL\pgsql\bin\pg_ctl.exe" `
    -Argument "start -D C:\PostgreSQL\pgsql\data -l C:\PostgreSQL\pgsql\data\postgres.log"
$pgTrigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "SmartFarm-PostgreSQL" `
    -Action $pgAction -Trigger $pgTrigger `
    -RunLevel Highest -Force | Out-Null
Write-Host "[OK] SmartFarm-PostgreSQL 등록 (부팅 시 자동 시작)"

# ── 2. FastAPI 서버 자동 시작 (부팅 후 60초) ──────────────────────────────
$apiAction = New-ScheduledTaskAction `
    -Execute $PYTHON `
    -Argument "-m uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level info" `
    -WorkingDirectory $APPDIR
$apiTrigger = New-ScheduledTaskTrigger -AtStartup
$apiTrigger.Delay = "PT60S"  # 60초 지연 (DB 먼저 시작)
Register-ScheduledTask -TaskName "SmartFarm-API" `
    -Action $apiAction -Trigger $apiTrigger `
    -RunLevel Highest -Force | Out-Null
Write-Host "[OK] SmartFarm-API 등록 (부팅 60초 후 시작)"

# ── 3. nginx 자동 시작 (부팅 후 90초) ────────────────────────────────────
$nginxAction = New-ScheduledTaskAction `
    -Execute "C:\nginx\nginx.exe" `
    -Argument "-c conf\nginx.conf" `
    -WorkingDirectory "C:\nginx"
$nginxTrigger = New-ScheduledTaskTrigger -AtStartup
$nginxTrigger.Delay = "PT90S"
Register-ScheduledTask -TaskName "SmartFarm-nginx" `
    -Action $nginxAction -Trigger $nginxTrigger `
    -RunLevel Highest -Force | Out-Null
Write-Host "[OK] SmartFarm-nginx 등록 (부팅 90초 후 시작)"

# ── 4. 증분 ETL (매일 새벽 2시) ───────────────────────────────────────────
$etlAction = New-ScheduledTaskAction `
    -Execute $PYTHON `
    -Argument "-m pipeline.incremental_etl --log-level INFO" `
    -WorkingDirectory $APPDIR
$etlTrigger = New-ScheduledTaskTrigger -Daily -At "02:00AM"
Register-ScheduledTask -TaskName "SmartFarm-ETL" `
    -Action $etlAction -Trigger $etlTrigger `
    -RunLevel Highest -Force | Out-Null
Write-Host "[OK] SmartFarm-ETL 등록 (매일 02:00)"

# ── 5. 모델 재학습 트리거 확인 (매일 새벽 3시) ───────────────────────────
$retrainAction = New-ScheduledTaskAction `
    -Execute $PYTHON `
    -Argument "-m pipeline.retrain_trigger" `
    -WorkingDirectory $APPDIR
$retrainTrigger = New-ScheduledTaskTrigger -Daily -At "03:00AM"
Register-ScheduledTask -TaskName "SmartFarm-Retrain" `
    -Action $retrainAction -Trigger $retrainTrigger `
    -RunLevel Highest -Force | Out-Null
Write-Host "[OK] SmartFarm-Retrain 등록 (매일 03:00)"

Write-Host ""
Write-Host "등록된 작업 확인:"
Get-ScheduledTask -TaskName "SmartFarm-*" | Select-Object TaskName, State | Format-Table
