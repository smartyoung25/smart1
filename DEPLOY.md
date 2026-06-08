# KAASA SmartOS 배포 가이드

## 1. 로컬 / 사내망 시연 (자동 재기동)
```
run_api_resilient.bat        REM uvicorn 자동 재기동 래퍼(다운 방지)
```
접속: http://localhost:8000/intro · 같은 망 모바일은 `releases/qr_intro.png` 스캔
(서버 IP 사용 시 http://<PC_IP>:8000/intro)

## 2. 운영 배포 (Docker — 자동복구 내장)
```
docker compose up -d                 # db·redis·api·nginx·mqtt (모두 restart: unless-stopped)
docker compose up -d certbot         # HTTPS 사용 시 Let's Encrypt 발급
```
- api 컨테이너는 `restart: unless-stopped` 로 크래시 자동 복구
- nginx 80/443, self-signed → 도메인 확보 후 certbot 공인 인증서 전환

## 3. HTTPS (공인 인증서) — 도메인 필요
1. 도메인 DNS A레코드 → 서버 IP
2. `nginx/nginx-ssl.conf` 의 server_name 도메인으로 수정
3. `docker compose up -d certbot` (발급·자동 갱신)

## 4. 외부 키 주입(.env) → 자동 실데이터 전환
| 키 | 효과 |
|----|------|
| NAAS_SOIL_API_URL / FARMMAP_API_URL | F2·F5 노지 실측 |
| ANTHROPIC_API_KEY | 챗봇 LLM 고도화 |
| (ERA5 CSV / KAMIS) | 모델·시세 정밀화 |

## 5. 성능 (실측 2026-06-04)
intro/smartos FCP ~450ms·14KB · c3_home FCP 480ms·64KB → LCP<3.0s 충족

## 릴리스
`releases/KAASA_SmartOS_v1.1.zip` (34화면+9컴포넌트) · `RELEASE_v1.1.md`

## 6. 무료 도메인 (nip.io) — 사내망 즉시 접속 (가입 불필요)
- 도메인: **192.168.35.87.nip.io** (이 PC LAN IP 자동 매핑, 계정 불필요)
- 접속: **http://192.168.35.87.nip.io:8000/intro** (검증 HTTP 200)
- 같은 망 모바일: `releases/qr_nipio.png` QR 스캔
- ⚠ 다른 기기에서 접속하려면 **방화벽 8000 인바운드 개방** 필요(관리자 PowerShell):
  ```
  New-NetFirewallRule -DisplayName "KAASA SmartOS 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
  ```
- (LAN IP가 바뀌면 새 IP로 `<새IP>.nip.io` 사용)

### 공개 인터넷 노출 (선택, 사용자 인프라)
nip.io는 사설 IP를 가리켜 Let's Encrypt 공인 인증서 발급 불가(LAN 전용).
공개 배포는 ① 공인 IP/포트포워딩 또는 ② 클라우드 서버 + 실도메인이 필요하며,
그 경우 `docker compose up -d` + certbot 으로 자동 HTTPS 완성.
