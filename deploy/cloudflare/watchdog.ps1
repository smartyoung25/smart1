# ============================================================
#  KAASA smartfarmingsight — 자동복구 watchdog
#  uvicorn(API 8000) + cloudflared(named tunnel) 가 죽으면 자동 재기동.
#  시스템 서비스 미사용. 작업 스케줄러(로그온 시) 로 기동 권장.
#  수동 실행:  powershell -ExecutionPolicy Bypass -File watchdog.ps1
#  중지: 이 프로세스 종료(작업관리자) 또는 스케줄 작업 해제.
# ============================================================
$ErrorActionPreference = "SilentlyContinue"

# ── 단일 인스턴스 가드 (중복 watchdog → cloudflared 중복기동·터널충돌 방지) ──
#   1차: 프로세스 기반 — 이미 다른 watchdog(-File ...watchdog.ps1)가 살아있으면 즉시 종료.
#        (Mutex만으로는 강제종료 시 'abandoned' 상태가 되어 중복 획득이 허용되던 문제 보완.)
$__selfPid = $PID
$__others = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessId -ne $__selfPid -and $_.CommandLine -like '*-File*watchdog.ps1*' })
if ($__others.Count -gt 0) {
    exit 0   # 이미 watchdog 가 돌고 있음
}
#   2차: 명명 Mutex — abandoned 예외도 '소유권 인계'로 정상 처리(직전 인스턴스 비정상 종료).
$global:__wdMutex = New-Object System.Threading.Mutex($false, "Global\KAASA_Watchdog_Singleton")
try {
    [void]$global:__wdMutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    # 직전 watchdog 가 mutex 보유 중 종료됨 → 본 인스턴스가 소유권 인계(정상 진행)
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
    # 중복 기동 방지: 이미 '포트 8000' uvicorn 프로세스가 있으면(느린 부팅 중 /health 미응답) 새로 띄우지 않음.
    #   ★ 포트 8000 한정 매칭 — 다른 포트(8001·8055 등 별개 프로젝트/프리뷰) uvicorn은 무시.
    #     (과거: 포트 무관 매칭이라 타 포트 uvicorn이 존재하면 8000 기동을 영구 생략 → farmingsight 502 원인.)
    $alive = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*uvicorn*api.main:app*' -and $_.CommandLine -match '--port\s+8000(\D|$)' })
    if ($alive.Count -gt 0) { Log "uvicorn(8000) 기동 중(부팅 대기) — 중복 기동 생략"; return }
    # 줄연속(백틱) 미사용 — 실행환경에서 백틱 유실 시 파싱오류로 재기동 실패하던 문제 방지
    $env:PYTHONPATH = $SMART; $env:PYTHONIOENCODING = "utf-8"; $env:PUBLIC_DEMO = "1"
    $apiArgs = @("-m","uvicorn","api.main:app","--host","0.0.0.0","--port","8000","--log-level","warning")
    try { Start-Process -WindowStyle Hidden -FilePath $PY -ArgumentList $apiArgs -WorkingDirectory $SMART; Log "uvicorn 재기동" }
    catch { Log "uvicorn 재기동 실패: $_" }
}

function Stop-Tunnel {
    # 좀비/끊긴 cloudflared 정리 — 새 인스턴스가 'credentials already in use'로 실패하는 것 방지
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

function Start-Tunnel {
    # RedirectStandardError 제거 — tunnel.log 파일잠금으로 Start-Process 실패하던 문제 방지
    $tunArgs = @("tunnel","--config",$CFG,"run",$TUN)
    try { Start-Process -WindowStyle Hidden -FilePath $CF -ArgumentList $tunArgs -WorkingDirectory $SMART; Log "cloudflared 재기동" }
    catch { Log "cloudflared 재기동 실패: $_" }
}

# 외부 연결성 검증: 공개 도메인 /health 가 200 이면 터널 정상.
#   프로세스 존재 체크만으로는 'cloudflared 는 살아있으나 edge 연결이 끊긴' 상태(530)를 못 잡음.
function Test-Tunnel {
    try { (Invoke-WebRequest "https://farmingsight.org/health" -UseBasicParsing -TimeoutSec 8).StatusCode -eq 200 }
    catch { $false }
}

Log "watchdog 시작"
$tunFail = 0
while ($true) {
    if (-not (Test-Api)) { Start-Api; Start-Sleep -Seconds 6 }

    $proc = [bool](Get-Process cloudflared -ErrorAction SilentlyContinue)
    if (-not $proc) {
        # 프로세스 자체가 없음 → 즉시 기동
        Start-Tunnel; $tunFail = 0; Start-Sleep -Seconds 8
    }
    elseif (Test-Api) {
        # 로컬은 정상인데 공개 도메인이 안 열리면 터널 연결만 끊긴 것 → 강제 재기동
        if (-not (Test-Tunnel)) {
            $tunFail++
            Log "터널 외부 연결 실패 ($tunFail/2) — 로컬 정상, edge 미연결"
            if ($tunFail -ge 2) {
                Log "터널 강제 재기동(좀비 정리 후)"
                Stop-Tunnel; Start-Sleep -Seconds 3; Start-Tunnel; $tunFail = 0; Start-Sleep -Seconds 8
            }
        } else { $tunFail = 0 }
    }
    Start-Sleep -Seconds 30
}
