# Cloudflare Tunnel 공개 배포 가이드

## ⚠️ 공개 전 필수 보안 조치 (중요)
현재 화면들은 **admin/1250 자동 로그인**을 사용합니다. 공개 인터넷에 노출하기 전 반드시:
1. **관리자 비밀번호 변경** — `admin/1250` → 강력한 비밀번호 (api/services/persistence 또는 DB)
2. **화면 자동로그인(_ensureToken admin/1250) 비활성화** → 실제 로그인 화면 경유로 전환
3. `JWT_SECRET_KEY` 환경변수 설정 (미설정 시 JWT 미들웨어 비활성 — 공개 시 위험)
4. CORS `ALLOWED_ORIGINS` 에 배포 도메인만 허용
→ 이 4가지 전에는 **사내망(nip.io)** 까지만 사용 권장.

## 배포 절차 (도메인이 Cloudflare에 있을 때)
```
deploy\cloudflare\setup_tunnel.bat   REM 단계별 안내
```
1. `winget install Cloudflare.cloudflared`
2. `cloudflared tunnel login` (도메인 인증)
3. `cloudflared tunnel create kaasa-smartos` → Tunnel ID/json 경로를 config.yml에 반영
4. `cloudflared tunnel route dns kaasa-smartos <도메인>`
5. API 기동(run_api_resilient.bat) 후:
   `cloudflared tunnel --config deploy\cloudflare\config.yml run kaasa-smartos`
→ **https://<도메인>/intro** 공개 HTTPS (인증서 자동, 포트포워딩 불필요)

## 장점
- 공인 IP·포트개방·별도 서버 불필요 (아웃바운드 터널)
- Cloudflare 자동 HTTPS·DDoS 보호
- 비용: 도메인비만 (터널·인증서 무료)
