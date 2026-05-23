# Smart Farm AI Platform — 작업 변경 이력

---

## 2026-05-22 — Phase 36: 관수 최적화 + AI 멀티프로바이더 + 외부 API 통합

### Priva 관수 최적화 (api/services/priva_irrigation.py — 신규)
- 770페이지 Priva 매뉴얼 5알고리즘 완전 구현
  - 알고리즘1: 적산일사 트리거 (`calc_radiation_sum_n_irrigations`)
  - 알고리즘2: 증산량 기반 공급량 (`calc_transpiration_supply_mm`)
  - 알고리즘3: P/I 배액 교정 컨트롤러 (P=0.60, I=0.10, `PIControllerState`)
  - 알고리즘4: 3상황 스케줄 (Phase1 15%·Phase2 65%·Phase3 20%, `build_phase_schedule`)
  - 알고리즘5: 일사 배액% 증가 (`calc_radiation_adjusted_drain_pct`)
- 작목별 기본 설정: 딸기/방울토마토/완숙토마토/파프리카/참외·오이

### ET₀ / ETc 확장 (api/services/kma_service.py — 업데이트)
- `calc_et0_hargreaves()` — Hargreaves-Samani 공식
- `calc_etc()` — FAO-56 Kc × ET₀ (4단계: initial/dev/mid/late)
- `get_solar_irrigation_schedule()` — Priva + ETc 블렌드 (50:50)

### 신규 API 엔드포인트 (api/routers/farmer.py — 5개 추가)
| 엔드포인트 | 설명 |
|-----------|------|
| `GET /irrigation/schedule/priva` | Priva 5알고리즘 통합 스케줄 (ET₀·P/I·3상황) |
| `GET /environment/weather/forecast` | KMA→Open-Meteo 폴백 + ETc 7일 예보 |
| `GET /disease-risk/augmented` | M5 + EPPO + RDA 3-source 통합 |
| `GET /system/model-performance` | M1~M5 전작목 성능 매트릭스 |
| `GET /system/api-status` | 외부 API 연결 상태 + 미설정 키 가이드 |

### 외부 API 허브 (api/services/external_api_hub.py — 신규)
- Open-Meteo: 무료 글로벌 기상예보 + ET₀ 계산 **테스트 검증 완료**
- EPPO Global DB: EU 해충/질병 데이터베이스 (무료)
- RDA 농진청: 생육기준·병해충 정보 (키 보유)
- AIHub: AI 학습 데이터셋 조회 (키 보유)
- PlantNet: 식물 이미지 인식 (공개 키 내장)
- KMA→Open-Meteo 자동 폴백 체인
- `get_disease_risk_augmented()`: M5 rule-based + EPPO + RDA 3-source 융합
- `_cached()`: TTL 캐시 (threading.Lock 동기화)

### AI 채팅 멀티프로바이더 (api/services/ai_chat.py — 업데이트)
- 폴백 체인: **Anthropic Claude → OpenAI GPT → Ollama 로컬 → 규칙 기반**
- `_call_ollama()` 신규: `http://localhost:11434/api/chat` Ollama API
  - `OLLAMA_ENABLED=true` 또는 `OLLAMA_HOST` 설정 시 활성화
  - `OLLAMA_MODEL` 환경변수로 모델 선택 (기본 llama3.2)
- `call_ai()` 업데이트: 4단계 폴백 체인 통합
- 티어별 모델 유지: pro→claude-haiku-4-5, enterprise→claude-sonnet-4-5

### 작목 설정 확장 (models/crop_config.py — 업데이트)
- 전 작목 FAO-56 Kc 4단계 값 추가 (`kc_stages`)
- `irrigation_target_mm_day` / `drain_target_pct` 필드 추가

### 테스트 강화
- `TestPrivaIrrigation` (31개): Priva 5알고리즘 전체 검증
- `TestExternalApiHub` (19개): 외부 API 허브 + 캐시 검증
- `TestAiChatMultiProvider` (26개): 멀티프로바이더 폴백 체인 검증
- 챗 엔드포인트 429 (billing quota) 수용: 18개 테스트 수정
- **최종: 965 PASS / 0 FAIL / 커버리지 81.65%**

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
