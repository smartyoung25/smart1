# 고정 주소 설정 — smartfarmos.app (확정안)

> 목표 공개 주소: **https://app.smartfarmos.app** (URL 안 바뀜·자동 HTTPS)
> `.app`은 구글 관리 TLD라 HTTPS가 강제되며, Cloudflare 터널이 이를 자동 제공합니다.

## 🙋 사용자님이 하실 일 (1회·약 10분)

### 1) 도메인 구매: `smartfarmos.app`
- 판매처(택1): Cloudflare Registrar(원가·추천) · 가비아 · Namecheap · Porkbun
- `.app` 대략 연 **$14~16(₩2만 내외)**
- (DNS 조회상 미등록 추정 — 구매 화면에서 최종 가용 확인)

### 2) Cloudflare 가입 + 도메인 추가
- cloudflare.com 무료 가입 → "Add a site" → `smartfarmos.app` 입력
- 안내되는 **네임서버 2개를 도메인 등록기관에 설정**(Cloudflare Registrar로 사면 자동)
- 네임서버 전파 완료까지 수분~수시간

### 3) 터널 생성·연결 (자동 스크립트 1줄)
```powershell
powershell -ExecutionPolicy Bypass -File deploy\cloudflare\setup_named_tunnel.ps1 -Domain app.smartfarmos.app
```
→ 브라우저에서 **Cloudflare 로그인 1회 승인**. 그 외 터널 생성·Tunnel ID 파싱·DNS 라우팅·config.yml 생성은 자동.

### 4) 상시 실행
```
deploy\cloudflare\run_named.bat
```
→ `https://app.smartfarmos.app/intro` 공개(PUBLIC_DEMO 읽기전용). 포트포워딩 불필요.
- 부팅 자동시작 원하면: `deploy\cloudflare\bin\cloudflared.exe service install`

## ✅ 제 쪽 준비 완료 (자동화된 부분)
- `setup_named_tunnel.ps1` (login→create→ID파싱→DNS→config 자동, `-Domain app.smartfarmos.app`)
- `run_named.bat` (API+터널 상시, PUBLIC_DEMO=1 유지)
- `bin/cloudflared.exe` (바이너리 보유)

## ⚠️ 제가 못 하는 부분 (정직히)
도메인 **구매·결제**, Cloudflare **계정 가입**, `tunnel login` **브라우저 인증**은
자격증명·결제 영역이라 제가 대신 수행할 수 없습니다 → 위 1~2단계는 직접.
3단계부터는 스크립트가 처리합니다.

## 결과
- 고정 주소 **https://app.smartfarmos.app** — 서버/PC 재시작해도 URL 불변
- 무료 퀵터널처럼 주소가 바뀌지 않음 / 자동 HTTPS / 포트포워딩 0
