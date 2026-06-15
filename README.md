# 🌿 Smart Farm AI Platform

스마트팜 환경 데이터 기반 수확량 예측 · 소득 최적화 · 운영 자동화 플랫폼

> **⚠️ 운영 배포 안내 (2026-06 기준)**
> 실가동 UI는 **모바일 화면 `screens/` (41화면)** 이며, 배포는 **Cloudflare named tunnel(`kaasa-smartos`) → uvicorn :8000** (nginx/docker 미사용)입니다.
> 구 PC 대시보드(`dashboard/`)는 **`archive/dashboard/`로 이관된 죽은 코드**로, 라우트(`/`·`/dashboard/*`)는 `/intro`로 차단됩니다.
> 아래 "빠른 시작 (Docker)" 등 docker/nginx 기준 설명은 **레거시 참고용**입니다. 운영 기준은 `CLAUDE.md`를 따르세요.

---

## 목차

1. [아키텍처 개요](#아키텍처-개요)
2. [빠른 시작 (Docker)](#빠른-시작-docker)
3. [환경변수 설명](#환경변수-설명)
4. [모델 개요](#모델-개요)
5. [ETL 파이프라인 운영](#etl-파이프라인-운영)
6. [재학습 트리거](#재학습-트리거)
7. [운영자 대시보드](#운영자-대시보드)
8. [API 엔드포인트](#api-엔드포인트)
9. [알림 설정](#알림-설정)
10. [bare-metal 배포 (systemd)](#bare-metal-배포-systemd)
11. [개발 환경 설정](#개발-환경-설정)
12. [트러블슈팅](#트러블슈팅)

---

## 아키텍처 개요

```
브라우저
  │
  ▼ :80
┌─────────────────────────────────────┐
│  nginx (리버스 프록시 + 대시보드)    │
│  / → dashboard/index.html           │
│  /api/* → api:8000                  │
└──────────────┬──────────────────────┘
               │
               ▼ :8000 (internal)
┌──────────────────────────────────────┐
│  FastAPI + uvicorn (2 workers)       │
│  /api/v1/recommend  — 환경 최적화    │
│  /api/admin/*       — 운영자 API     │
│  /health            — 헬스체크       │
└──────────┬───────────────────────────┘
           │  model_artifacts (volume)
           ▼
┌──────────────────────────────────────┐
│  Pipeline (cron)                     │
│  02:00 — ETL CSV 처리                │
│  03:00 — 재학습 임계값 체크          │
└──────────────────────────────────────┘
```

**지원 작물**: 딸기 · 방울토마토 · 완숙토마토 · 참외 · 파프리카

---

## 빠른 시작 (Docker)

### 사전 요구사항
- Docker Engine 24+
- Docker Compose v2+
- 여유 디스크 2GB 이상

### 1. 저장소 클론 및 환경 설정

```bash
git clone <repo-url> smart_farm
cd smart_farm

cp .env.example .env
```

`.env` 파일에서 **반드시** 변경해야 할 항목:

```bash
# JWT 서명 키 — 반드시 교체 (openssl rand -hex 32)
JWT_SECRET_KEY=your_secret_here

# 관리자 패스워드
ADMIN_PASSWORD=your_strong_password
```

### 2. 모델 아티팩트 시딩

```bash
make seed-models
```

모델 파일(`models/artifacts/`)을 Docker named volume으로 복사합니다.

### 3. 전체 스택 시작

```bash
make up-all
# 또는
docker compose up -d
```

### 4. 접속 확인

| URL | 설명 |
|-----|------|
| http://localhost | 운영자 대시보드 |
| http://localhost/docs | Swagger UI (API 문서) |
| http://localhost/health | API 헬스체크 |

```bash
make health   # → {"status":"ok","version":"0.2.0"}
```

---

## 환경변수 설명

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `NGINX_PORT` | `80` | nginx 외부 포트 |
| `API_PORT` | `8000` | API 내부 포트 (직접 노출 안 함) |
| `JWT_SECRET_KEY` | — | **필수** — `openssl rand -hex 32` |
| `ADMIN_USERNAME` | `admin` | 대시보드 로그인 사용자명 |
| `ADMIN_PASSWORD` | — | **필수** — 강력한 패스워드 설정 |
| `ALLOWED_ORIGINS` | `http://localhost,...` | CORS 허용 오리진 |
| `ETL_DATA_DIR` | `./etl_data` | 신규 CSV 파일 수신 디렉토리 |
| `ETL_CRON_SCHEDULE` | `0 2 * * *` | ETL 실행 cron (매일 02:00) |
| `RETRAIN_CRON_SCHEDULE` | `0 3 * * *` | 재학습 체크 cron (매일 03:00) |
| `RETRAIN_ENV_ROWS` | `500` | 환경 데이터 재학습 임계값 |
| `RETRAIN_PROD_ROWS` | `200` | 생산량 데이터 재학습 임계값 |
| `SLACK_WEBHOOK_URL` | — | Slack 알림 웹훅 URL (비어있으면 비활성) |
| `NOTIFY_EMAIL_TO` | — | 이메일 수신자 (비어있으면 비활성) |
| `NOTIFY_ENV` | `production` | 알림 메시지에 표시할 환경 이름 |

---

## 모델 개요

### M1 — 생육 예측 (XGBoost + LightGBM 앙상블)

온도·습도·CO₂·일사량 등 환경 센서 일별 데이터로 생육 지수를 예측합니다.

### M2 — 수확량 예측 (Optuna 튜닝 앙상블)

시즌 집계 환경 데이터 + GDD(Growing Degree Days) + 분산 피처로 수확량(kg)을 예측합니다.

| 작물 | MAPE | 비고 |
|------|------|------|
| 딸기 | 19.8% | |
| 방울토마토 | 8.8% | |
| 완숙토마토 | 17.1% | |
| 참외 | 8.7% | |
| 파프리카 | 11.8% | |

### 소득 최적화

M2 예측값 + KAMIS 시장 가격 + 농가별 비용 구조를 결합해  
최적 온도·습도·CO₂ 조합을 추천합니다.

---

## ETL 파이프라인 운영

### CSV 파일 명명 규칙

새로운 센서/생산 데이터는 아래 형식으로 `ETL_DATA_DIR`에 넣으면 자동 처리됩니다:

```
{farm_id}__{작물명}__{시즌}__{유형}.csv

예시:
  farm001__딸기__1__env.csv    ← 환경 센서 데이터
  farm001__딸기__1__prod.csv   ← 생산량 데이터
  farm002__strawberry__2__env.csv  ← 영문 작물명도 지원
```

**지원 작물명**: `딸기`, `방울토마토`, `완숙토마토`, `참외`, `파프리카`  
(영문 별칭: `strawberry`, `cherry_tomato`, `tomato`, `melon`, `paprika`)

### 수동 ETL 실행

```bash
# 드라이런 (실제 처리 없이 로그만 확인)
docker compose exec pipeline \
  python3 -B pipeline/run_etl_dir.py /app/etl_data --dry-run

# 실제 실행
docker compose exec pipeline \
  python3 -B pipeline/run_etl_dir.py /app/etl_data
```

처리 완료된 파일은 `etl_data/done/` 디렉토리로 이동됩니다.

---

## 재학습 트리거

### 자동 트리거

매일 03:00 cron이 `pipeline/state/new_rows_since_retrain.json`을 읽어  
임계값(`RETRAIN_ENV_ROWS` / `RETRAIN_PROD_ROWS`) 초과 시 재학습을 실행합니다.

### 수동 재학습

```bash
# 특정 작물만
docker compose exec pipeline \
  python3 -B pipeline/retrain_trigger.py --force --crops 딸기 방울토마토

# 전체 작물
docker compose exec pipeline \
  python3 -B pipeline/retrain_trigger.py --force
```

### 재학습 이력 확인

```bash
cat pipeline/state/retrain_history.json | python3 -m json.tool
```

---

## 운영자 대시보드

`http://localhost` 에 접속하면 로그인 화면이 나타납니다.

- **사용자명**: `.env`의 `ADMIN_USERNAME` (기본: `admin`)
- **패스워드**: `.env`의 `ADMIN_PASSWORD`

대시보드에서 확인 가능한 정보:
- API 온라인/오프라인 상태 및 버전
- 작물별 모델 R² · MAPE 배지
- ETL 신규 행 누적 진행률 (임계값 대비 %)
- ETL 로그 실시간 tail (30줄)
- 재학습 이력 (트리거 사유, 대상 작물, 성공/실패)

API URL은 대시보드 상단 입력란에서 변경할 수 있어  
원격 서버의 API도 모니터링할 수 있습니다.

---

## API 엔드포인트

### 인증

```bash
# JWT 토큰 발급
curl -X POST http://localhost/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your_password"}'
# → {"access_token":"eyJ...","token_type":"bearer"}
```

이후 모든 `/api/admin/*` 요청에 헤더를 포함하세요:
```
Authorization: Bearer eyJ...
```

### 주요 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/health` | API 헬스체크 |
| `POST` | `/api/v1/auth/token` | JWT 토큰 발급 |
| `POST` | `/api/v1/recommend` | 환경 최적화 추천 |
| `GET` | `/api/admin/overview` | 플랫폼 전체 현황 |
| `GET` | `/api/admin/models/crops` | 작물별 모델 상세 |
| `GET` | `/api/admin/pipeline/state` | 재학습 임계값 진행률 |
| `GET` | `/api/admin/pipeline/etl-status` | ETL 로그 tail |
| `GET` | `/api/admin/pipeline/retrain-history` | 재학습 이력 |

전체 API 문서: **http://localhost/docs**

---

## 알림 설정

### Slack

1. [Slack Incoming Webhooks](https://api.slack.com/messaging/webhooks) 에서 웹훅 URL 생성
2. `.env` 에 추가:
   ```bash
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
   NOTIFY_ENV=production
   ```
3. `docker compose up -d` 재시작

알림이 발송되는 이벤트:
- 재학습 임계값 초과 (시작 전)
- 작물별 재학습 완료 / 실패
- ETL 처리 오류

### 이메일 (Gmail 예시)

```bash
NOTIFY_EMAIL_TO=ops@yourcompany.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-app@gmail.com
SMTP_PASSWORD=your_app_password   # Gmail 앱 패스워드 사용
SMTP_FROM=smartfarm@yourcompany.com
```

두 값 모두 비어있으면 알림이 완전히 비활성화됩니다 (외부 호출 없음).

---

## bare-metal 배포 (systemd)

Docker 없이 Linux 서버에 직접 배포하는 경우:

```bash
# 1. 프로젝트 설치
sudo cp -r . /opt/smart_farm
cd /opt/smart_farm

# 2. Python 가상환경 생성
python3 -m venv venv
venv/bin/pip install -r requirements.api.txt

# 3. .env 설정
cp .env.example .env && vim .env

# 4. systemd 서비스 설치
sudo bash deploy/install_systemd.sh
```

설치 후 관리:

```bash
# 상태 확인
systemctl status smart-farm-api
systemctl status smart-farm-etl.timer
systemctl status smart-farm-retrain.timer

# 수동 ETL 실행
systemctl start smart-farm-etl.service

# 로그 확인
journalctl -u smart-farm-api -f
tail -f /opt/smart_farm/logs/etl.log
```

---

## 개발 환경 설정

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경변수 (개발용)
cp .env.example .env
# JWT_SECRET_KEY 없으면 인증 자동 비활성화

# API 서버 실행 (개발 모드)
uvicorn api.main:app --reload --port 8000

# 테스트
pytest tests/ -v
```

### make 타깃 목록

```bash
make help
```

| 타깃 | 설명 |
|------|------|
| `build` | Docker 이미지 빌드 |
| `up-all` | 전체 스택 시작 (권장) |
| `down` | 전체 종료 |
| `logs` | API 로그 팔로우 |
| `logs-pipeline` | 파이프라인 로그 |
| `logs-nginx` | nginx 로그 |
| `health` | 헬스체크 |
| `seed-models` | 모델 아티팩트 볼륨 시딩 |
| `clean` | 이미지·볼륨 전체 삭제 |

---

## 트러블슈팅

### API가 시작하지 않음

```bash
docker compose logs api
# → "JWT_SECRET_KEY 환경변수가 설정되지 않았습니다"
#   .env 파일에 JWT_SECRET_KEY 설정 후 재시작
```

### 대시보드 로그인 실패

```bash
# 개발 환경에서 ADMIN_PASSWORD 미설정 시 기본값 "changeme" 사용
# .env의 ADMIN_PASSWORD와 일치하는지 확인
docker compose exec api env | grep ADMIN
```

### ETL 파일이 처리되지 않음

```bash
# 파일명 규칙 확인
python3 -B pipeline/run_etl_dir.py ./etl_data --dry-run

# 일반적인 원인:
# - 작물명 오타 (banana, 딸기 등 지원 목록 확인)
# - 언더스코어 2개(__) 구분자 누락
# - .csv 확장자 누락
```

### 재학습이 실행되지 않음

```bash
# 현재 누적 행 수 확인
cat pipeline/state/new_rows_since_retrain.json

# 강제 실행
docker compose exec pipeline \
  python3 -B pipeline/retrain_trigger.py --force --crops 딸기
```

### nginx 502 Bad Gateway

```bash
# API 헬스체크 확인
docker compose ps
docker compose logs api | tail -20

# API가 아직 시작 중인 경우 30초 대기 후 재확인
```

### 모델 아티팩트 볼륨이 비어있음

```bash
make seed-models
docker compose restart api
```

---

## 프로젝트 구조

```
smart_farm/
├── api/                    # FastAPI 애플리케이션
│   ├── main.py             # 앱 진입점, 미들웨어
│   ├── routers/            # 엔드포인트 (admin, farmer, auth, recommend)
│   ├── middleware/         # JWT 인증 미들웨어
│   ├── schemas/            # Pydantic 모델
│   └── services/           # 비즈니스 로직
├── engine/                 # 최적화 엔진
│   └── profit_optimizer.py # 소득 최적화 (M2 + 비용 모델)
├── models/                 # ML 모델 레이어
│   ├── m1_growth.py        # 생육 예측
│   ├── m2_yield.py         # 수확량 예측
│   └── artifacts/          # 학습된 모델 파일 (볼륨)
├── pipeline/               # 데이터 파이프라인
│   ├── incremental_etl.py  # 증분 ETL (단일 파일)
│   ├── run_etl_dir.py      # ETL 디렉토리 스캐너 (cron)
│   ├── retrain_trigger.py  # 재학습 자동 트리거
│   ├── model_gate.py       # 모델 배포 게이트 (MAPE ≥5%p 개선)
│   ├── notifier.py         # Slack/이메일 알림
│   └── train/              # 학습 스크립트 (v4 Optuna-tuned)
├── adapters/               # 데이터 소스 어댑터
├── dashboard/              # 운영자 대시보드 (단일 HTML)
├── nginx/                  # nginx 설정
├── deploy/                 # systemd unit 파일 + 설치 스크립트
├── Dockerfile              # API 이미지 (멀티스테이지)
├── Dockerfile.pipeline     # 파이프라인 이미지
├── docker-compose.yml      # 3-서비스 스택
├── startup.sh              # 파이프라인 컨테이너 entrypoint
├── Makefile                # 개발자 단축 명령
└── .env.example            # 환경변수 템플릿
```
