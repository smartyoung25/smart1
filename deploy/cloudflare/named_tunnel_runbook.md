# Cloudflare Named Tunnel — 상시 공개 (추천 · 포트포워딩 불필요)

**왜 추천**: 아웃바운드 터널이라 **공유기 포트포워딩 불필요**(CGNAT·ISP 차단 영향 없음).
고정 도메인 + 자동 HTTPS + 무료. cloudflared 바이너리 이미 `deploy/cloudflare/bin/cloudflared.exe`.

## 🙋 당신이 할 일 (한 번만)
1. **도메인 확보** + **Cloudflare 등록**:
   - 도메인이 있으면: cloudflare.com 가입 → 도메인 추가 → 네임서버를 Cloudflare로 변경
   - 없으면: 저가 도메인 구매(가비아 등 ~₩1만/년) 후 위와 동일
2. 아래 명령을 순서대로 1회 실행(로그인은 브라우저 인증):

```bat
set CF=deploy\cloudflare\bin\cloudflared.exe
%CF% tunnel login                          :: 브라우저에서 도메인 선택·인증
%CF% tunnel create kaasa-smartos           :: 출력된 Tunnel ID·credentials json 경로 확인
%CF% tunnel route dns kaasa-smartos app.your-domain.com
```
3. `deploy/cloudflare/config.yml` 의 `{TUNNEL_ID}`·`{DOMAIN}`(=app.your-domain.com) 치환.

## 실행 (상시)
```bat
deploy\cloudflare\run_named.bat
```
→ `https://app.your-domain.com/intro` 공개 HTTPS (포트포워딩 0).

## 자동 시작(선택, 서비스 등록)
```bat
%CF% service install
%CF% tunnel run kaasa-smartos
```
부팅 시 자동 기동. API는 `run_api_resilient.bat`(루트)로 자동 재시작.

## 보안
- 데모: `PUBLIC_DEMO=1`(쓰기·관리자 차단) / 실서비스: 해제 + 강력 `JWT_SECRET_KEY`
- `.env` 키 커밋 금지

## 경로 비교
| 방식 | 포트포워딩 | 도메인 | HTTPS | 안정성 |
|------|-----------|--------|-------|--------|
| **Named Tunnel(추천)** | ❌ 불필요 | Cloudflare 등록 도메인 | 자동 | ★★★ |
| DuckDNS+Caddy | ✅ 필요(80/443) | 무료 .duckdns.org | 자동(LE) | ★★ (포트포워딩 가능 시) |
| 퀵터널(현재) | ❌ | 랜덤 trycloudflare | 자동 | ★ (재시작 시 URL 변경) |
