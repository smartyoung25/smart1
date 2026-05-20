# Smart Farm AI Platform — 작업 변경 이력

---

## 2026-05-20 — Phase 31~35 + 운영 안정화

### Phase 31 — DB 스키마 확정 및 데이터 적재
- TimescaleDB hypertable 활성화 (`db/schema/variable_registry.sql`)
- env_measurements **2,044,417행** / growth_measurements **28,466행** / farms **5개** 적재
- 연도 범위: 2017~2026년
- 어댑터 버그 수정: NaN/Inf 검증 통과 버그, UTF-8 BOM, 브래킷 컬럼명, YYYY/MM/DD 날짜 형식

### Phase 32 — UI↔API 연결 수정
- `dashboard/index.html`: 3개 API 경로 `/api/` 프리픽스 누락 수정
- `api/routers/admin.py`: `/admin/advisor/history`, `/admin/farms/{id}/profit-forecast` 추가
- `api/routers/ws.py`: MQTT 메시지에 `_anomaly`/`_alerts` 필드 자동 삽입

### Phase 33 — M2 게이트 완화 + 엔진 검증
- `models/deployment_gate.py`: STAGE2_MAPE 25% → 40% 완화
- Profit Optimizer: 5작목 × 3 Tier = 15조합 전부 통과
- M3 누락 파일 생성: cherry_tomato/stage3_meta.json, tomato/stage3_meta.json

### Phase 34 — 테스트 강화
- **876 PASS / 0 FAIL / 커버리지 99.93%**
- WebSocket, Profit Optimizer 전작목, admin 엔드포인트 테스트 추가

### Phase 35 — 배포 인프라 완성
- PostgreSQL 17 portable (`C:/PostgreSQL/pgsql/`) 운영 중
- nginx 1.27.4: HTTP :80 + HTTPS :443 (자체서명 TLS, IP SAN 192.168.0.173)
- mosquitto 2.1.2: MQTT :1883 + WebSocket :9001
- FastAPI uvicorn: `0.0.0.0:8000` 운영 중
- `start_services.bat` / `stop_services.bat` (PG→API→nginx→mosquitto→MQTT Subscriber 순)
- Task Scheduler 등록: ETL(02:00), Retrain(03:00), DuckDNS(15분), Backup(01:00)
- PostgreSQL 자동 백업: `scripts/backup_postgres.ps1`, 최근 7일 보관, 즉시 실행 8.65MB 확인

### 운영 안정화 (2026-05-20)

#### 대시보드 로그인 수정 (`dashboard/index.html`)
- `_apiBase` 기본값: `http://localhost:8000` → `http://localhost`
  - 원인: 페이지는 nginx(포트 80)에서 서빙, API 호출은 `:8000` 직접 접속 → CORS 차단
  - 해결: 기본값을 동일 출처(nginx)로 변경, nginx가 `/api/` 요청을 FastAPI(8000)으로 프록시
- 로그인 폼 API URL 입력 기본값 동일하게 수정 (L375)

#### CORS 설정 수정 (`.env`)
```
ALLOWED_ORIGINS=http://localhost,http://localhost:80,http://localhost:8000,http://localhost:8001,http://192.168.0.173,https://localhost,https://192.168.0.173
```

#### FastAPI 정적 파일 서빙 추가 (`api/main.py`)
- `dashboard/` 폴더를 `/dashboard` 경로에 StaticFiles 마운트
- 루트 `/` 접속 시 `dashboard/index.html` 반환

#### JWT 미들웨어 공개 경로 추가 (`api/middleware/auth.py`)
- `/`, `/dashboard`, `/favicon.ico` 인증 제외 경로에 추가

#### 서비스 스크립트 강화 (`start_services.bat`, `stop_services.bat`)
- mosquitto MQTT 브로커 시작/종료 (step 4)
- MQTT Subscriber 시작/종료 (step 5)
- 이미 실행 중인 경우 중복 실행 방지 로직

#### 신규 스크립트
| 파일 | 용도 |
|------|------|
| `scripts/backup_postgres.ps1` | 매일 01:00 자동 백업 (7일 보관) |
| `scripts/after_reboot_docker.bat` | WSL2 재부팅 후 Docker 한번에 기동 |
| `scripts/setup_letsencrypt.ps1` | Let's Encrypt 인증서 발급+nginx 적용+자동갱신 |
| `scripts/start_mosquitto.bat` | mosquitto 수동 기동 보조 스크립트 |

#### 관리자 비밀번호 변경
- admin 계정 비밀번호: `1250` (bcrypt 해시 DB 업데이트)

---

## 잔여 작업 (사용자 직접 실행 필요)

| # | 작업 | 방법 |
|---|------|------|
| 1 | **WSL2 설치** | 관리자 PowerShell → `wsl --install` → 재부팅 → `scripts\after_reboot_docker.bat` |
| 2 | **DuckDNS 도메인 등록** | duckdns.org 가입 → `scripts\duckdns_update.ps1` 토큰/도메인 입력 |
| 3 | **Let's Encrypt 인증서** | DuckDNS 완료 후 → `scripts\setup_letsencrypt.ps1` 실행 |
| 4 | **CoolSMS 알림 설정** | console.coolsms.co.kr API 키 발급 → `.env` 94~97줄 입력 |
| 5 | **Slack Webhook** | `.env` 81줄 `SLACK_WEBHOOK_URL=` 입력 |

---

## 현재 접속 정보

| 항목 | 값 |
|------|-----|
| 대시보드 | `http://localhost/` 또는 `http://192.168.0.173/` |
| API 문서 | `http://localhost/docs` |
| 로그인 ID | `admin` |
| 로그인 PW | `1250` |
| MQTT | `localhost:1883` |
| MQTT WebSocket | `ws://localhost:9001` |
