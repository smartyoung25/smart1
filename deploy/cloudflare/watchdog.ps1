# ============================================================
#  KAASA smartfarmingsight — 자동복구 watchdog
#  uvicorn(API 8000) + cloudflared(named tunnel) 가 죽으면 자동 재기동.
#  시스템 서비스 미사용. 작업 스케줄러(로그온 시) 로 기동 권장.
#  수동 실행:  powershell -ExecutionPolicy Bypass -File watchdog.ps1
#  중지: 이 프로세스 종료(작업관리자) 또는 스케줄 작업 해제.
# ============================================================
$ErrorActionPreference = "SilentlyContinue"

# ── 단일 인스턴스 가드 (중복 watchdog → cloudflared 중복기동·터널충돌 방지) ──
$global:__wdMutex = New-Object System.Threading.Mutex($false, "Global\KAASA_Watchdog_Singleton")
if (-not $global:__wdMutex.WaitOne(0)) {
    # 이미 다른 watchdog 가 돌고 있음 → 즉시 종료
    exit 0
}

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
    # 줄연속(백틱) 미사용 — 실행환경에서 백틱 유실 시 파싱오류로 재기동 실패하던 문제 방지
    $env:PYTHONPATH = $SMART; $env:PYTHONIOENCODING = "utf-8"; $env:PUBLIC_DEMO = "1"
    $apiArgs = @("-m","uvicorn","api.main:app","--host","0.0.0.0","--port","8000","--log-level","warning")
    try { Start-Process -WindowStyle Hidden -FilePath $PY -ArgumentList $apiArgs -WorkingDirectory $SMART; Log "uvicorn 재기동" }
    catch { Log "uvicorn 재기동 실패: $_" }
}

function Start-Tunnel {
    # RedirectStandardError 제거 — tunnel.log 파일잠금으로 Start-Process 실패하던 문제 방지
    $tunArgs = @("tunnel","--config",$CFG,"run",$TUN)
    try { Start-Process -WindowStyle Hidden -FilePath $CF -ArgumentList $tunArgs -WorkingDirectory $SMART; Log "cloudflared 재기동" }
    catch { Log "cloudflared 재기동 실패: $_" }
}

Log "watchdog 시작"
while ($true) {
    if (-not (Test-Api)) { Start-Api; Start-Sleep -Seconds 6 }
    if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) { Start-Tunnel; Start-Sleep -Seconds 6 }
    Start-Sleep -Seconds 30
}
