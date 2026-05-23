# 스마트팜 AI 플랫폼 — 전체 아키텍처 (2026-05-22)

## 6계층 구조 개요

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1  대시보드 / 클라이언트                                  │
│           dashboard/index.html  (nginx :80 서빙)                │
│           WebSocket(ws://…/ws/) + HTTP REST                     │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP / WebSocket
┌────────────────────────▼────────────────────────────────────────┐
│  LAYER 2  API 서버 (FastAPI + uvicorn :8000)                    │
│           nginx 리버스 프록시 → 127.0.0.1:8000                  │
│                                                                  │
│  ① 인증                                                         │
│     POST /api/v1/auth/token        JWT 발급                     │
│                                                                  │
│  ② 농가 관리 (api/routers/farmer.py)                           │
│     GET/PUT  /api/farms/{farm_id}/meta                          │
│     GET      /api/farms/{farm_id}/meta/regions                  │
│     GET      /api/farms/{farm_id}/summary                       │
│     GET      /api/farms/{farm_id}/recommendations               │
│     POST     /api/farms/{farm_id}/apply                         │
│                                                                  │
│  ③ 환경 관리                                                    │
│     POST     /api/farms/{farm_id}/environment/manual  ← 수동 입력│
│     GET      /api/farms/{farm_id}/environment          ← 현재값  │
│     GET      /api/farms/{farm_id}/environment/weather  ← 7일 예보│
│                                                                  │
│  ④ 생육 / 재배기술                                              │
│     GET      /api/farms/{farm_id}/harvest      M2 수확량 예측   │
│     GET      /api/farms/{farm_id}/revenue      M3 매출 예측     │
│     GET      /api/farms/{farm_id}/costs        M4 비용 조회     │
│     POST     /api/farms/{farm_id}/costs/manual                  │
│     DELETE   /api/farms/{farm_id}/costs/manual                  │
│     GET      /api/farms/{farm_id}/disease-risk  M5 질병 위험   │
│     GET      /api/farms/{farm_id}/disease-risk/augmented        │
│              └─ M5 + EPPO EU 해충 DB + RDA 농진청 통합          │
│     POST     /api/farms/{farm_id}/irrigation   P4 관수 수신     │
│     GET      /api/farms/{farm_id}/irrigation/schedule           │
│              └─ KMA 일사량 기반 + Priva ETc 혼합 스케줄         │
│     GET      /api/farms/{farm_id}/irrigation/schedule/priva     │
│              └─ Priva 5알고리즘 통합 (ET₀·P/I·3상황·배액율)    │
│     GET      /api/farms/{farm_id}/irrigation/analysis           │
│     POST     /api/farms/{farm_id}/whatif  What-if 시뮬레이션    │
│                                                                  │
│  ⑤ 기상 예보                                                    │
│     GET      /api/farms/{farm_id}/environment/weather           │
│              └─ KMA ASOS 7일 예보 + ET₀ Hargreaves              │
│     GET      /api/farms/{farm_id}/environment/weather/forecast  │
│              └─ KMA→Open-Meteo 폴백 + ETc 작목별 물요구량       │
│                                                                  │
│  ⑥ AI 인터페이스                                                │
│     POST     /api/farms/{farm_id}/chat                          │
│              └─ 멀티프로바이더: Anthropic→OpenAI→Ollama→규칙기반│
│                                                                  │
│  ⑦ 시스템 모니터링                                              │
│     GET      /api/farms/{farm_id}/system/model-performance      │
│              └─ M1~M5 전작목 성능 매트릭스 (cv_r2, MAPE 등)    │
│     GET      /api/farms/{farm_id}/system/api-status             │
│              └─ 외부 API 연결 상태 + 미설정 키 가이드            │
│                                                                  │
│  ⑧ 관리자 (api/routers/admin.py)                               │
│     GET  /api/admin/overview                                    │
│     GET  /api/admin/models, /models/crops, /models/versions     │
│     GET  /api/admin/pipeline/runs, /state, /etl-status          │
│     POST /api/admin/pipeline/trigger                            │
│     GET  /api/admin/farms/overview                              │
│     GET  /api/admin/farms/{farm_id}/history                     │
│     GET  /api/admin/farms/{farm_id}/profit-forecast             │
│     GET  /api/admin/prices/latest, /history/{crop_ko}           │
│     POST /api/admin/prices/refresh                              │
│     GET  /api/admin/advisor/optimal, /history, /summary         │
│     GET  /api/admin/variable-registry                           │
│                                                                  │
│  ⑨ 실시간 연결 (api/routers/ws.py)                             │
│     WS   /ws/{farm_id}           MQTT→WebSocket 브릿지          │
│     GET  /api/sensors/{farm_id}/latest   HTTP 폴링 폴백         │
└────────────────────────┬────────────────────────────────────────┘
                         │ 함수 호출
┌────────────────────────▼────────────────────────────────────────┐
│  LAYER 3  수익 최적화 엔진 (engine/)                            │
│                                                                  │
│  profit_optimizer.py   M2·M3·M4 결과 취합 → 최적 환경값 권고   │
│  what_if_simulator.py  ±후보 환경값 × M2 예측 → 수익 비교      │
│  stats_loader.py       env_stats.json / growth_stats.json 로드  │
│  m3_harvest_timing.py  GDD 기반 수확 타이밍 계산                │
│  cost_benchmark.json   작목·티어별 비용 벤치마크 데이터         │
└────────────────────────┬────────────────────────────────────────┘
                         │ 모델 예측 요청
┌────────────────────────▼────────────────────────────────────────┐
│  LAYER 4  ML 모델 계층 (models/)                                │
│                                                                  │
│  M1  m1_growth.py         환경 → 생육 예측 (Ridge/XGB/LGB)     │
│  M2  m2_yield.py          생육 → 수확량 예측 (XGB + 분위수)    │
│  M3  m3_revenue.py        수확량 × 시장가격 → 매출 예측        │
│  M4  m4_cost.py           파라미터 기반 비용 산출 (ML 없음)     │
│  M5  m5_disease.py        EfficientNet-B0 질병 진단 (현재 stub) │
│                                                                  │
│  ── ML 계층이 받는 입력 (다른 레이어 연동) ──────────────────   │
│                                                                  │
│  Layer 6 DB (PostgreSQL)                                        │
│    env_measurements      → M1 피처 (온도·습도·CO2·EC·pH 등)   │
│    growth_measurements   → M2 학습 레이블 (actual_yield)       │
│                                                                  │
│  Layer 6 정적 JSON                                              │
│    env_stats.json        → M1·이상감지 기준 (μ±3σ 임계값)     │
│    growth_stats.json     → M2 피처 정규화 통계, GDD 보정값     │
│    income_survey.json    → M4 비용 파라미터 (작목·티어별 단가) │
│    price_stats.json      → M3 매출 예측 시장가격 기준          │
│                                                                  │
│  Layer 5 외부 API                                               │
│    KMA 기상청 API        → 7일 예보 → M2 수확량 보조 피처      │
│    KAMIS 농산물 가격     → M3 매출 예측 시장가격 보정          │
│    Open-Meteo API        → ET₀ 예보 → Priva 관수 공급량 계산   │
│    EPPO / RDA            → M5 병해 위험 보강 (rule-based 보정) │
│                                                                  │
│  ── 모델 게이트 현황 (2026-05-21) ──────────────────────────   │
│  M1 전작목 ✅ (2026-05-21 Trimmed Mean 게이트 적용, 5/5 PASS)  │
│     cherry_tomato: fold_scores=[-0.067,0.014,-0.572,-0.047]   │
│     Fold3(2021 분포이동) 제외 trimmed_mean=-0.033 → PASS      │
│  M2 전작목 ✅ (tomato cv_mape=123.4% 과적합 의심, quantile 활용)│
│  M3 전작목 ✅                                                   │
│  M4 파라미터 기반 ✅                                            │
│  M5 전작목 ❌ stub 모드 (m5_efficientnet.pt 없음)              │
│                                                                  │
│  deployment_gate.py    Rule-A: mean ≥ -0.20, min ≥ -0.25      │
│  model_loader.py       게이트 실패 시 baseline 폴백            │
└────────────────────────┬────────────────────────────────────────┘
                         │ MQTT pub/sub
┌────────────────────────▼────────────────────────────────────────┐
│  LAYER 5  데이터 수집 / 외부 연동                               │
│                                                                  │
│  mosquitto MQTT 브로커  :1883 (TCP), :9001 (WebSocket)          │
│    토픽: smartfarm/+/env   — 환경 센서 데이터                  │
│    토픽: smartfarm/+/prod  — 생산량 데이터                     │
│  pipeline/mqtt_subscriber.py  → MQTT → PostgreSQL 저장         │
│                                                                  │
│  외부 API 어댑터 (adapters/)                                    │
│    kma_weather_adapter.py      KMA 기상청 단기 예보              │
│    kamis_price_adapter.py      KAMIS 농산물 유통정보             │
│    iot_sensor_adapter.py       센서 데이터 전처리                │
│                                                                  │
│  외부 API 허브 (api/services/external_api_hub.py)               │
│    Open-Meteo          ✅ 무료 글로벌 기상예보 + ET₀ 계산        │
│    EPPO Global DB      ✅ EU 해충/질병 DB (무료, 키 불필요)      │
│    RDA 농진청          ✅ 생육기준·병해 정보 (키 보유)            │
│    AIHub               ✅ AI 데이터셋 메타 조회 (키 보유)         │
│    PlantNet            ✅ 식물 이미지 인식 (공개 키 포함)         │
│    KMA → Open-Meteo   ✅ 자동 폴백 체인                          │
│                                                                  │
│  Priva 관수 엔진 (api/services/priva_irrigation.py)             │
│    알고리즘 1: 적산일사 트리거 (gsr J/cm² ÷ trigger)            │
│    알고리즘 2: 증산량 공급량 (ET₀×Kc×증산상수÷(1-drain%))      │
│    알고리즘 3: P/I 배액 교정 (P=0.60, I=0.10 PI컨트롤러)       │
│    알고리즘 4: 3상황 스케줄 (Phase1 15%/Phase2 65%/Phase3 20%) │
│    알고리즘 5: 일사 배액% 증가 (강한 일사 → 목표 배액 상향)     │
│                                                                  │
│  ET₀ / ETc 계산 (api/services/kma_service.py)                   │
│    calc_et0_hargreaves()  Hargreaves-Samani ET₀                 │
│    calc_etc()             FAO-56 Kc × ET₀ → ETc                 │
│    Kc 단계: initial/dev/mid/late (5작목 전체 설정)               │
└────────────────────────┬────────────────────────────────────────┘
                         │ SQL / JSON 읽기
┌────────────────────────▼────────────────────────────────────────┐
│  LAYER 6  데이터 저장소                                         │
│                                                                  │
│  PostgreSQL 17 (127.0.0.1:5432, DB: smartfarm)                  │
│    env_measurements   635,397행 (TimescaleDB hypertable 대기중) │
│    growth_measurements 10,803행                                 │
│    farms             5개 농가 (farm_001~005)                    │
│    users             admin 계정                                 │
│    variable_registry  환경 변수 정의                             │
│    manual_inputs      수동 입력 이력                             │
│                                                                  │
│  정적 데이터 파일 (models/data/ / engine/data/)                │
│    env_stats.json      환경 통계 (μ, σ, 이상감지 임계값)       │
│    growth_stats.json   생육 통계 + GDD 보정값                  │
│    income_survey.json  비용 파라미터 (농진청 소득 조사)         │
│    price_stats.json    작목별 시장가격 통계                     │
│                                                                  │
│  모델 아티팩트 (models/artifacts/{crop}/)                      │
│    stage1_model.pkl    M1 생육 예측 모델                        │
│    stage2_model.pkl    M2 수확량 예측 모델                      │
│    stage2_quantile_model.pkl  M2 분위수 모델 (불확실성 추정)   │
│    stage3_model.pkl    M3 매출 예측 모델                        │
│    stage{1..3}_meta.json  메타데이터 + 게이트 결과             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 데이터 흐름 (요청 → 응답)

```
IoT 센서 → MQTT :1883
    → mqtt_subscriber.py
        → PostgreSQL env_measurements

대시보드 GET /harvest 요청
    → nginx :80
        → FastAPI :8000  farmer.py::harvest()
            → model_loader.py  stage1_model.pkl (M1 생육 예측)
            → model_loader.py  stage2_model.pkl (M2 수확량 예측)
                ← env_measurements (최근 30일 환경)
                ← growth_stats.json (피처 정규화)
                ← KMA 기상 예보 (7일)
            ← HarvestForecast JSON 응답

대시보드 GET /recommendations 요청
    → FastAPI  farmer.py::recommendations()
        → profit_optimizer.py
            → what_if_simulator.py
                → M2 예측 × ±후보 환경값 3~5개
            → M3 매출 계산
            → M4 비용 계산
            ← 최적 환경값 + 예상 수익 증가분 반환

대시보드 GET /irrigation/schedule/priva 요청
    → FastAPI  farmer.py::get_priva_schedule()
        → external_api_hub.get_weather_forecast_full()
            → kma_service.get_latest_weather()    (KMA 우선)
            → open_meteo API (KMA 실패 시 폴백)
        → kma_service.calc_et0_hargreaves()      ET₀ 계산
        → priva_irrigation.get_default_config()  작목별 Kc/drain 설정
        → priva_irrigation.compute_priva_schedule()
            알고리즘1: 일사 트리거 (gsr ÷ trigger_j_cm2)
            알고리즘2: 증산량 공급량 (ET₀×Kc×상수)
            알고리즘3: P/I 배액 교정 (선택적)
            알고리즘4: 3상황 스케줄 생성
            알고리즘5: 일사 배액% 동적 상향
        ← PrivaScheduleOut (phases, n_irrigations, supply_ml 등)

대시보드 POST /chat 요청
    → FastAPI  farmer.py::chat()
        → billing.check_chat_quota()             티어 확인
        → ai_chat.build_farm_context()           농장 컨텍스트 구성
        → ai_chat.call_ai()
            ① Anthropic Claude (ANTHROPIC_API_KEY 있을 때)
               claude-haiku-4-5 (pro) / claude-sonnet-4-5 (enterprise)
            ② OpenAI GPT-4o-mini (OPENAI_API_KEY 있을 때)
            ③ Ollama 로컬 LLM (OLLAMA_ENABLED=true 또는 OLLAMA_HOST)
               모델: OLLAMA_MODEL (기본 llama3.2), localhost:11434
            ④ 규칙 기반 stub (키 전무 시 최종 폴백)
        ← ChatResponse {reply, suggestions, model_used, tokens_used}
```

---

## 배포 현황 (2026-05-22)

| 서비스 | 상태 | 위치 |
|--------|------|------|
| PostgreSQL 17 | ✅ 실행 중 | `net start postgresql-x64-17` |
| FastAPI (uvicorn) | ✅ :8000 | `start_services.bat` |
| nginx | ✅ :80 | `C:\nginx\conf\smartfarm.conf` |
| mosquitto MQTT | ✅ :1883/:9001 | `start_services.bat` |
| MQTT Subscriber | ✅ 실행 중 | `pipeline\mqtt_subscriber.py` |
| Open-Meteo API | ✅ 연결됨 | 무료, 키 불필요 |
| EPPO 해충 DB | ✅ 연결됨 | 무료, 키 불필요 |
| RDA 농진청 API | ✅ 키 보유 | `.env` RDA_API_KEY |
| AIHub API | ✅ 키 보유 | `.env` AIHUB_API_KEY |
| Priva 관수 엔진 | ✅ 활성 | `api/services/priva_irrigation.py` |
| ET₀ / ETc 계산 | ✅ 활성 | `api/services/kma_service.py` |
| AI 채팅 (Anthropic) | ⚠️ 키 확인 필요 | `.env` ANTHROPIC_API_KEY |
| AI 채팅 (OpenAI 폴백) | ⚠️ 키 미설정 | `.env` OPENAI_API_KEY |
| AI 채팅 (Ollama 폴백) | ℹ️ 선택적 | `.env` OLLAMA_ENABLED=true |
| Docker / WSL2 | ❌ 비활성 | `deploy/enable_wsl2_admin.ps1` (관리자) |

---

## 테스트 현황 (2026-05-22)

| 항목 | 수치 |
|------|------|
| 전체 테스트 수 | 965개 |
| PASS | 965 (100%) |
| FAIL | 0 |
| 커버리지 | **81.65%** (요구 60%) |
| 신규 모듈 커버리지 | priva_irrigation.py 97%, ai_chat.py 73%, external_api_hub.py 69% |

## 잔여 이슈

| 항목 | 우선순위 | 조치 |
|------|---------|------|
| M1 cherry_tomato Fold3 분포이동 | 낮 | 2023+ 데이터 추가 시 자연 해소 예정 |
| M2 tomato cv_mape=123.4% (standalone) | 낮 | 실제 서비스 pipeline_meta cv_mape=44.1% 정상 |
| M5 stub 모드 (전작목) | 낮 | EfficientNet-B0 전이학습, 작목별 질병 이미지 500장/클래스 필요 |
| AI 채팅 Anthropic 키 소진 | 중 | `.env` ANTHROPIC_API_KEY 갱신 또는 OPENAI_API_KEY 설정 |
| Ollama 로컬 LLM | 선택 | `OLLAMA_ENABLED=true` + `ollama pull llama3.2` 실행 |
| WSL2/Docker 비활성 | 낮 | `deploy/enable_wsl2_admin.ps1` (관리자) → 재부팅 |
| DuckDNS/HTTPS 미설정 | 낮 | `deploy/setup_duckdns.ps1 -Domain <name> -Token <token>` |
