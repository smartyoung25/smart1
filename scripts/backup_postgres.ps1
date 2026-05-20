# Smart Farm — PostgreSQL 자동 백업 스크립트
# Task Scheduler로 매일 새벽 1시 실행
# 보관: 최근 7일치만 유지

$PGSQL    = "C:\PostgreSQL\pgsql"
$BACKUP_DIR = "C:\smart_farm\backups\db"
$DB_NAME  = "smartfarm"
$DB_USER  = "smartfarm"
$KEEP_DAYS = 7

$env:PGPASSWORD = "f6bFuazrDJkHJsLfiI7@"

# 백업 디렉터리 생성
if (!(Test-Path $BACKUP_DIR)) {
    New-Item -ItemType Directory -Force $BACKUP_DIR | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupFile = "$BACKUP_DIR\${DB_NAME}_${timestamp}.dump"
$logFile    = "C:\smart_farm\logs\backup.log"

function Write-Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

Write-Log "백업 시작: $backupFile"

# pg_dump 실행 (custom 포맷 — 압축, 병렬 복원 가능)
& "$PGSQL\bin\pg_dump.exe" `
    -h 127.0.0.1 -U $DB_USER -d $DB_NAME `
    -F c -Z 6 `
    -f $backupFile 2>&1 | ForEach-Object { Write-Log $_ }

if ($LASTEXITCODE -eq 0) {
    $sizeMB = [Math]::Round((Get-Item $backupFile).Length / 1MB, 2)
    Write-Log "백업 완료: $backupFile ($sizeMB MB)"
} else {
    Write-Log "[ERROR] 백업 실패 (exit $LASTEXITCODE)"
    exit 1
}

# 오래된 백업 삭제 (7일 초과)
$cutoff = (Get-Date).AddDays(-$KEEP_DAYS)
$old = Get-ChildItem "$BACKUP_DIR\*.dump" | Where-Object { $_.LastWriteTime -lt $cutoff }
foreach ($f in $old) {
    Remove-Item $f.FullName -Force
    Write-Log "오래된 백업 삭제: $($f.Name)"
}

Write-Log "백업 완료. 현재 보관 수: $((Get-ChildItem "$BACKUP_DIR\*.dump").Count)개"
