# Cloudflare Named Tunnel — 운영 터널 운용

> **★ 현재 운영은 iwinv Ubuntu(115.68.226.231)가 서빙한다.**
> 터널: iwinv 의 systemd `cloudflared-kaasa.service` → `/root/.cloudflared/config.yml`.
> **이 PC(개발기)는 평시에 터널에 붙지 않는다.** 이 문서의 아래 절차는
> ① 신규 환경 세팅 ② **iwinv 장애 시 수동 페일오버** 용도다.

## ⚠ 왜 조심해야 하나 (2026-07-17 실제 사고)

이 PC 와 iwinv 는 **같은 터널 UUID**를 쓴다. 두 곳에서 cloudflared 가 동시에 뜨면
Cloudflare 가 트래픽을 **양쪽에 나눠 보낸다**. 실제로 watchdog 이 이 PC 의 cloudflared 를
되살려 운영 요청 **10/10 이 이 PC(개발 코드)로** 갔고, iwinv 배포분이 사용자에게 닿지 않았다.

**증상이 조용하다** — 도메인은 200 이고 SW 버전도 같다. 동작 차이로만 드러났다
(`/tasks/daily` 가 iwinv 는 `P5`, 이 PC 는 `None`).

**배포·장애 판정 시 반드시 두 경로를 대조할 것:**
```bash
ssh … 'curl -s localhost:8000/health'          # iwinv 실체
curl -s https://farmingsight.org/health        # 터널이 실제로 보는 곳
cloudflared tunnel info kaasa-smartos          # 연결자 목록(ORIGIN IP)으로 확정
```
`tunnel info` 의 ORIGIN IP 가 `115.68.226.231` 하나면 정상.

**왜 이 PC 에 자격증명을 남겨뒀나**: `~/.cloudflared/cert.pem`·`<UUID>.json` 이 있어야
페일오버가 가능하다. 대신 `config.yml` 은 placeholder 로 두고 `run_named.bat` 에 확인
프롬프트를 걸어, **의도적으로만** 붙게 했다.

## 🙋 당신이 할 일 (계정·도메인만 — 나머지 자동)
1. **도메인 확보** + **Cloudflare 등록**:
   - 도메인이 있으면: cloudflare.com 가입 → 도메인 추가 → 네임서버를 Cloudflare로 변경
   - 없으면: 저가 도메인 구매(가비아 등 ~₩1만/년) 후 위와 동일
2. **턴키 스크립트 1회 실행** (도메인만 넘기면 생성·DNS·config.yml 자동):
```bat
powershell -ExecutionPolicy Bypass -File deploy\cloudflare\setup_named_tunnel.ps1 -Domain app.your-domain.com
```
   → 브라우저 로그인 창만 1회 승인. 그 외 터널 생성·Tunnel ID 파싱·DNS 라우팅·`config.yml` 생성 전부 자동.

(수동으로 하려면: `cloudflared tunnel login/create/route dns` 후 `config.yml` 의 `{TUNNEL_ID}`·`{DOMAIN}` 치환)

## 🚨 페일오버 — iwinv 장애 시 이 PC 로 임시 전환

> 평시에는 절대 실행하지 말 것. 아래는 iwinv 가 죽었을 때만.

**1) iwinv 상태 확인** — 정말 죽었는지 먼저 본다
```bash
ssh -i ~/.ssh/kaasa_iwinv_ed root@115.68.226.231 'systemctl is-active cloudflared-kaasa; curl -s -o /dev/null -w "%{http_code}" localhost:8000/health'
```

**2) ★ iwinv 연결자를 먼저 끊는다** (접속 가능하면)
```bash
ssh … 'systemctl stop cloudflared-kaasa'
```
> 이 단계를 건너뛰면 **두 연결자가 공존해 트래픽이 갈라진다** — 사고와 같은 상태가 된다.
> iwinv 에 아예 접속이 안 되면 연결자도 죽었을 가능성이 크다. `cloudflared tunnel info`
> 의 ORIGIN IP 목록으로 확인 후 진행.

**3) 이 PC 준비**
```bash
git pull                                    # 운영과 같은 코드여야 한다
# config.yml 의 placeholder 치환: {TUNNEL_ID}·{CREDENTIALS_FILE}·{DOMAIN}
#   TUNNEL_ID:       cloudflared tunnel info kaasa-smartos 의 ID
#   CREDENTIALS_FILE: C:\Users\<user>\.cloudflared\<UUID>.json
#   DOMAIN:          farmingsight.org
```

**4) 기동**
```bat
deploy\cloudflare\run_named.bat        REM 경고 확인 후 YES 입력
```

**5) 검증** — 연결자가 이 PC 하나인지
```bash
cloudflared tunnel info kaasa-smartos   # ORIGIN IP 가 이 PC 공인IP 단 1개여야 함
curl -s https://farmingsight.org/health
```

**6) iwinv 복구 후 원상복구** (순서 중요)
```bash
# ① 이 PC: cloudflared 종료 → config.yml 을 placeholder 로 되돌림(커밋 상태로 복원)
git checkout deploy/cloudflare/config.yml
# ② iwinv: 연결자 재기동
ssh … 'systemctl start cloudflared-kaasa'
# ③ 검증: tunnel info 의 ORIGIN IP 가 115.68.226.231 하나
```

## ❌ 하지 말 것
- `cloudflared service install` — 이 PC 에 터널을 **영구** 설치해 사고를 상시화한다.
  운영 터널 영속은 iwinv 의 systemd 가 담당한다.
- `watchdog.ps1` 로 터널 자동 재기동 — 제거됨(2026-07-17). watchdog 은 로컬
  uvicorn:8000 전용이며, cloudflared 발견 시 경고 로그만 남긴다.

## 보안
- 데모: `PUBLIC_DEMO=1`(쓰기·관리자 차단) / 실서비스: 해제 + 강력 `JWT_SECRET_KEY`
- `.env` 키 커밋 금지

## 현재 구성

| 구분 | 평시(운영) | 페일오버(임시) |
|------|-----------|---------------|
| 서빙 | iwinv Ubuntu 115.68.226.231 (Docker) | 이 PC (개발기) |
| 터널 | iwinv systemd `cloudflared-kaasa.service` | `run_named.bat` 수동 |
| config | `/root/.cloudflared/config.yml` | `deploy/cloudflare/config.yml` (평시 placeholder) |
| 자격증명 | iwinv `/root/.cloudflared/` | 이 PC `~/.cloudflared/` (페일오버용 보존) |

> 두 연결자가 **동시에** 뜨면 트래픽이 갈라진다 — 반드시 한쪽만.
