# KAASA SmartOS 퍼블리싱 런북 (역할분담)

## 0. 현재 상태
- ✅ 앱(41화면)+백엔드(22 API) · PUBLIC_DEMO 읽기전용 보안 · JWT 회전
- ✅ **PWA 설치형**(manifest·SW·아이콘, 오프라인 캐시) · 자체 모니터링 · 오프라인 배너
- ✅ 임시 공개(Cloudflare 퀵터널) 라이브

## 1. 🤖 코드/설정 (내가 완료 — 자격증명 불필요)
- PWA: `/manifest.webmanifest`·`/sw.js`·`/icon.svg` (루트 스코프, data.js 자동 등록)
- 보안: PUBLIC_DEMO(쓰기·관리자 403), JWT 회전, 텔레메트리 수집은 비인증 허용/집계는 인증
- 배포 자산: `deploy/cloudflare/{config.yml(템플릿)·demo_live.bat·setup_tunnel.bat}`, `deploy/`(systemd·nginx·Let's Encrypt·DuckDNS)
- 점검: `scripts/check_integrations.py`(연동 상태), `/api/telemetry/summary`(에러 관측)

## 2. 🙋 당신 액션 (계정·구매·비밀)
| 단계 | 할 일 | 비고 |
|------|-------|------|
| (a) 도메인 | 가비아/후이즈 구매 **또는 무료 DuckDNS** | DuckDNS면 비용 0 |
| (b) Cloudflare | 가입 → 도메인 등록(상시 named tunnel·HTTPS) | 퀵터널은 계정 불필요(임시만) |
| (c) API 키 | 흙토람(NAAS)·위성(Sentinel)·LLM(Anthropic)·알림(Slack/CoolSMS/SMTP) 발급 | `docs/INTEGRATION_GUIDE.md` |
| (d) `.env` 입력 | 위 키를 서버 `.env`에 직접 입력(비밀) | 내가 대신 입력 불가 |
| (e) 호스팅 | 현 PC 상시가동 vs 클라우드 VM 결정 | |

## 3. 상시 공인 도메인 + HTTPS 전환 (B)
도메인·Cloudflare 준비 후:
```bat
deploy\cloudflare\setup_tunnel.bat        :: cloudflared 로그인·터널 생성
:: 출력된 Tunnel ID·json 경로를 config.yml의 {TUNNEL_ID}에 반영
cloudflared tunnel route dns kaasa-smartos your.domain.com
:: 보안 기동(상시)
set PUBLIC_DEMO=        :: 실서비스면 해제(쓰기 허용) / 데모면 1 유지
set JWT_SECRET_KEY=<강력한 무작위>
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
cloudflared tunnel --config deploy\cloudflare\config.yml run kaasa-smartos
```
→ `https://your.domain.com/intro` 공개 HTTPS. (대안: Linux면 `deploy/systemd` + nginx + Let's Encrypt)

## 4. 키 주입 후 검증 (D — 내가 수행)
당신이 `.env`에 키 입력 후 알려주면:
```
python scripts/check_integrations.py   :: 🟢 LIVE 전환 확인
```
흙토람·위성·LLM·알림이 Mock/프록시 → 실측으로 자동 전환됨을 검증.

## 5. 임시 공개(지금 가능, 계정 불필요)
```bat
deploy\cloudflare\demo_live.bat   :: PUBLIC_DEMO 읽기전용 + 퀵터널 → trycloudflare URL
```

## 보안 체크리스트(공개 전 필수)
- [ ] PUBLIC_DEMO 정책 결정(데모=1 / 실서비스=해제+인증강화)
- [ ] JWT_SECRET_KEY 무작위 회전
- [ ] `.env` 비공개(.gitignore 확인 — 키 커밋 금지)
- [ ] check_integrations.py로 의도한 연동만 활성 확인
