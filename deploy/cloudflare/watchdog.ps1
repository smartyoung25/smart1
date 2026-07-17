# ============================================================
#  KAASA Farmingsight — 로컬 개발 API 자동복구 watchdog
#  로컬 uvicorn(API 8000) 이 죽거나 행(hang) 이면 재기동한다.
#
#  ★★ cloudflared(터널) 는 관리하지 않는다 — 절대 되살리지 말 것.
#     2026-07-05 운영은 iwinv Ubuntu 서버로 이전됐고, 이 PC 의 config.yml 은
#     iwinv 와 **같은 터널 UUID** 를 쓴다. 이 PC 에서 cloudflared 를 띄우면
#     farmingsight.org 트래픽이 이 PC(개발 코드)로 넘어온다.
#     2026-07-17 실제 사고: 이 watchdog 이 cloudflared 를 되살려 운영 요청
#     10/10 이 전부 이 PC 로 갔고, iwinv 배포분이 사용자에게 닿지 않았다.
#     증상이 조용하다 — 도메인은 200 이고 SW 버전도 같아 동작 차이로만 드러났다.
#     ※ 구 Test-Tunnel 은 https://farmingsight.org/health 를 찔렀는데, 이제 그 응답은
#       iwinv 가 준다. 즉 이 PC 터널이 끊겨 있어도 200 이라 '정상'으로 오판한다.
#       터널 상태 판정 자체가 성립하지 않으므로 제거했다.
#     운영 터널 장애는 iwinv 의 systemd(cloudflared-kaasa.service)가 담당한다.
#
#  시스템 서비스 미사용. 수동 실행:
#     powershell -ExecutionPolicy Bypass -File watchdog.ps1
#  중지: 이 프로세스 종료(작업관리자) 또는 스케줄 작업 해제.
# ============================================================
$ErrorActionPreference = "SilentlyContinue"

# ── 단일 인스턴스 가드 (중복 watchdog → uvicorn 중복기동·포트 충돌 방지) ──
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
$WDLOG = "$SMART\deploy\cloudflare\watchdog.log"
# ★ cloudflared 경로·config·터널명 상수는 두지 않는다 — 남겨두면 '되붙여도 된다'는
#   오해를 준다. 이 PC 는 운영 터널에 붙지 않는다(헤더 참조).

function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Out-File -FilePath $WDLOG -Append -Encoding utf8 }

function Test-Api {
    try { (Invoke-WebRequest "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 4).StatusCode -eq 200 }
    catch { $false }
}

# 포트 8000 uvicorn 프로세스 목록. ★ 8000 한정 — 타 포트(8001·8055 등 별개 프로젝트/프리뷰)는 무시.
#   (과거: 포트 무관 매칭이라 타 포트 uvicorn 존재 시 8000 기동을 영구 생략 → farmingsight 502 원인.)
function Get-ApiProcs {
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*uvicorn*api.main:app*' -and $_.CommandLine -match '--port\s+8000(\D|$)' })
}

function Start-Api {
    # 중복 기동 방지: 이미 '포트 8000' uvicorn 프로세스가 있으면(느린 부팅 중 /health 미응답) 새로 띄우지 않음.
    if ((Get-ApiProcs).Count -gt 0) { Log "uvicorn(8000) 기동 중(부팅 대기) — 중복 기동 생략"; return }
    # 줄연속(백틱) 미사용 — 실행환경에서 백틱 유실 시 파싱오류로 재기동 실패하던 문제 방지
    $env:PYTHONPATH = $SMART; $env:PYTHONIOENCODING = "utf-8"; $env:PUBLIC_DEMO = "1"
    $apiArgs = @("-m","uvicorn","api.main:app","--host","0.0.0.0","--port","8000","--log-level","warning")
    try { Start-Process -WindowStyle Hidden -FilePath $PY -ArgumentList $apiArgs -WorkingDirectory $SMART; Log "uvicorn 재기동" }
    catch { Log "uvicorn 재기동 실패: $_" }
}

# ★ cloudflared 를 기동/재기동하는 함수는 두지 않는다(위 헤더 참조).
#   있으면 언젠가 호출된다 — 실제로 그래서 운영을 가로챘다.

# 이 PC 에 cloudflared 가 떠 있으면 운영 트래픽을 가로채는 중이다.
#   ※ 임의로 죽이지 않고 경고만 남긴다 — watchdog 이 남의 프로세스를 예고 없이
#     종료하는 건 놀라운 동작이다. 조치는 사람이 판단한다.
function Warn-IfTunnelRunning {
    if (Get-Process cloudflared -ErrorAction SilentlyContinue) {
        Log "[경고] 이 PC 에서 cloudflared 실행 중 — farmingsight.org 트래픽을 가로챌 수 있음(운영은 iwinv). 확인 후 종료 요망"
    }
}

Log "watchdog 시작 (로컬 uvicorn:8000 전용 — cloudflared 미관리)"
$apiFail = 0
while ($true) {
    if (Test-Api) {
        $apiFail = 0
    } else {
        $apiFail++
        $procs = Get-ApiProcs
        # 8000 프로세스가 존재하는데도 4사이클(약 2분+) 무응답 → 행(hang)/데드락 판단 → 강제 종료 후 재기동.
        #   (부팅 지연은 보통 1~2사이클 내 응답 → 넉넉한 유예. 재기동 안 하면 hang 서버가 영구 502.)
        if ($procs.Count -gt 0 -and $apiFail -ge 4) {
            Log "8000 무응답 ${apiFail}회 지속 — 행(hang) 판단, 강제 종료 후 재기동"
            $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Start-Sleep -Seconds 2
            Start-Api; Start-Sleep -Seconds 6
            $apiFail = 0
        } else {
            Start-Api; Start-Sleep -Seconds 6
        }
    }

    Warn-IfTunnelRunning
    Start-Sleep -Seconds 30
}
