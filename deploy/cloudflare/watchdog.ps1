# ============================================================
#  KAASA smartfarmingsight — 자동복구 watchdog
#  uvicorn(API 8000) + cloudflared(named tunnel) 가 죽으면 자동 재기동.
#  시스템 서비스 미사용. 작업 스케줄러(로그온 시) 로 기동 권장.
#  수동 실행:  powershell -ExecutionPolicy Bypass -File watchdog.ps1
#  중지: 이 프로세스 종료(작업관리자) 또는 스케줄 작업 해제.
# ============================================================
$ErrorActionPreference = "SilentlyContinue"
$SMART = "C:\smart_farm"
$PY    = "C:\tools\python311\python.exe"
$CF    = "$SMART\deploy\cloudflare\bin\cloudflared.exe"
$CFG   = "$SMART\deploy\cloudflare\config.yml"
$TUN   = "kaasa-smartos"
$CFLOG = "$SMART\deploy\cloudflare\tunnel.log"
$WDLOG = "$SMART\deploy\cloudflare\watchdog.log"

function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Out-File -FilePath $WDLOG -Append -Encoding utf8 }

function Test-Api {
    try { (Invoke-WebRequest "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 4).StatusCode -eq 200 }
    catch { $false }
}

function Start-Api {
    $env:PYTHONPATH = $SMART; $env:PYTHONIOENCODING = "utf-8"; $env:PUBLIC_DEMO = "1"
    Start-Process -WindowStyle Hidden -FilePath $PY `
        -ArgumentList "-m","uvicorn","api.main:app","--host","0.0.0.0","--port","8000","--log-level","warning" `
        -WorkingDirectory $SMART
    Log "uvicorn 재기동"
}

function Start-Tunnel {
    Start-Process -WindowStyle Hidden -FilePath $CF `
        -ArgumentList "tunnel","--config",$CFG,"run",$TUN `
        -RedirectStandardError $CFLOG -WorkingDirectory $SMART
    Log "cloudflared 재기동"
}

Log "watchdog 시작"
while ($true) {
    if (-not (Test-Api)) { Start-Api; Start-Sleep -Seconds 6 }
    if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) { Start-Tunnel; Start-Sleep -Seconds 6 }
    Start-Sleep -Seconds 30
}
