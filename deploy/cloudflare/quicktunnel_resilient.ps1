# KAASA SmartOS — 무료 퀵터널 상시 유지(자동 재기동 + 공개 URL 자동기록)
# 계정·도메인·포트포워딩 불필요. URL은 current_url.txt 에 항상 최신으로 기록됨.
# 사용: powershell -ExecutionPolicy Bypass -File deploy\cloudflare\quicktunnel_resilient.ps1
$ErrorActionPreference = "SilentlyContinue"
$ROOT = "C:\smart_farm"
$PY   = "C:\tools\python311\python.exe"
$CF   = "$ROOT\deploy\cloudflare\bin\cloudflared.exe"
$URLFILE = "$ROOT\deploy\cloudflare\current_url.txt"
$env:PUBLIC_DEMO = "1"                                  # 읽기전용 공개(데모)
$env:JWT_SECRET_KEY = "kaasa_" + [guid]::NewGuid().ToString("N")
$env:PYTHONPATH = $ROOT; $env:PYTHONIOENCODING = "utf-8"
Set-Location $ROOT

# 1) API 기동(없으면)
if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port 8000 -InformationLevel Quiet)) {
    Start-Process -WindowStyle Minimized $PY "-m uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level warning"
    Start-Sleep 6
}

# 2) 퀵터널 루프 — 죽으면 재기동, 새 URL을 파일에 기록
while ($true) {
    Write-Host "[tunnel] 시작…"
    $log = "$ROOT\deploy\cloudflare\_tunnel.log"
    if (Test-Path $log) { Remove-Item $log -Force }
    $p = Start-Process $CF "tunnel --url http://localhost:8000 --no-autoupdate --logfile `"$log`"" -PassThru -WindowStyle Minimized
    # URL 추출(최대 30초 대기)
    for ($i=0; $i -lt 30; $i++) {
        Start-Sleep 1
        $u = (Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1).Matches.Value
        if ($u) { Set-Content $URLFILE $u; Write-Host "[tunnel] 공개 URL: $u  (→ current_url.txt)"; break }
    }
    $p.WaitForExit()                                    # 터널이 죽으면
    Write-Host "[tunnel] 종료 감지 — 5초 후 재기동(새 URL 발급)"
    Start-Sleep 5
}
