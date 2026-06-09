# DuckDNS 무료 도메인 + 자동 HTTPS 상시 공개

**비용 0원**으로 `https://<당신>.duckdns.org` 공개 주소를 운영합니다.
(도메인 구매 불필요 · Caddy가 Let's Encrypt 인증서 자동 발급·갱신)

## 구성 파일 (이미 준비됨)
| 파일 | 역할 |
|------|------|
| `Caddyfile` | 자동 HTTPS 리버스 프록시(→ localhost:8000) + 보안헤더 + 캐싱 |
| `duckdns_update.ps1` | 공인 IP를 DuckDNS에 5분 주기 갱신 |
| `start_live.bat` | API 기동 + DuckDNS 갱신 + Caddy 실행 원클릭 |

## 🙋 당신이 할 4가지 (자격증명·물리)
1. **DuckDNS 가입**: https://www.duckdns.org (구글/깃허브 로그인) → 서브도메인 생성(예 `kaasafarm`) → **토큰 복사**
2. **값 입력**:
   - `duckdns_update.ps1` → `$SUBDOMAIN`, `$TOKEN`
   - `Caddyfile` → `{SUBDOMAIN}` 치환
   - `start_live.bat` → `JWT_SECRET_KEY` 무작위로 변경
3. **공유기 포트포워딩**: 외부 80·443 → 이 PC 내부IP (HTTPS 인증서 발급에 필요)
4. **Caddy 다운로드**: https://caddyserver.com/download (windows amd64) → `caddy.exe`를 `deploy\duckdns\`에 저장

## 실행
```bat
deploy\duckdns\start_live.bat
```
→ 수 초 내 `https://<서브도메인>.duckdns.org/intro` 공개 HTTPS.

## 상시 자동화(선택)
- DuckDNS 갱신: 작업 스케줄러 5분 주기 (`duckdns_update.ps1` 하단 주석 명령)
- 서버 자동 재시작: `run_api_resilient.bat`(루트) 또는 systemd(리눅스)

## 보안
- 데모 공개면 `start_live.bat`에서 `set PUBLIC_DEMO=1` 활성(쓰기·관리자 차단)
- 실서비스면 PUBLIC_DEMO 해제 + 강력한 `JWT_SECRET_KEY` 필수
- `.env` 키는 절대 커밋 금지(.gitignore 확인)

## 대안
- 포트포워딩이 불가한 환경 → Cloudflare named tunnel(도메인을 Cloudflare에 등록) 또는 클라우드 VM(오라클 무료티어 등). `docs/PUBLISH_RUNBOOK.md` 참조.
