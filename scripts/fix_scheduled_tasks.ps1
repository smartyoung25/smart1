# SmartFarm 예약 작업 수정 스크립트
# ETL: incremental_etl.py(CSV전용) → nightly_db_etl.py(DB→Parquet)
# Retrain: wrapper cmd 사용

# SmartFarm-ETL 업데이트
$etlAction = New-ScheduledTaskAction `
    -Execute "C:\tools\python311\python.exe" `
    -Argument "-m pipeline.nightly_db_etl" `
    -WorkingDirectory "C:\smart_farm"
Set-ScheduledTask -TaskName "SmartFarm-ETL" -Action $etlAction
Write-Host "SmartFarm-ETL 업데이트 완료"

# SmartFarm-Retrain 확인 (이미 올바른 스크립트 사용 중)
$retrain = Get-ScheduledTask -TaskName "SmartFarm-Retrain"
Write-Host "SmartFarm-Retrain 현재 작업: $($retrain.Actions[0].Execute) $($retrain.Actions[0].Arguments)"

# 수동 테스트 실행
Write-Host ""
Write-Host "=== ETL 수동 테스트 ==="
Push-Location C:\smart_farm
& C:\tools\python311\python.exe -m pipeline.nightly_db_etl
Pop-Location
