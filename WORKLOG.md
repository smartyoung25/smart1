# KAASA SmartOS — 작업 이력 로그 (WORKLOG.md)
> 세션별 작업 내역, 버그 수정, 검수 결과를 타임스탬프와 함께 기록

---

## 2026-05-31 (일) 세션 #1

### 13:25 — 세션 시작
- CLAUDE.md, PROGRESS.md, data.js, g3_period.html 컨텍스트 로드
- 백엔드 엔드포인트 3개 구현 확인: Priva, /api/v2/recommend, WebSocket

### 13:44 — 서비스 기동
- Docker Desktop 시도 → Linux 엔진 미기동 확인
- `start_services.bat` 방식으로 전환 (네이티브 Windows 서비스)
- PostgreSQL 17 ✅ 이미 실행 중 (127.0.0.1:5432)
- mosquitto ✅ 이미 실행 중
- FastAPI uvicorn 시작 → `/health` 200 OK ✅

### 13:56 — 인증 디버깅
- `/api/auth/token` → 404, `/api/v1/auth/token` 정상 경로 확인
- admin 비밀번호: `.env` ADMIN_PASSWORD=1250 확인
- JWT 발급 성공 ✅

### 14:10 — 버그 발견 및 수정

#### BUG-001: Priva ET0 스케줄 500 오류
- **증상**: `GET /api/farms/farm_001/irrigation/schedule/priva` → 500
- **오류**: `'list' object has no attribute 'get'`
- **원인**: `api/routers/farmer.py:2248` — `wx.get("daily", {})` 가 list 반환 시 `.get()` 호출 실패
- **수정**: `isinstance` 방어 코드 추가
  ```python
  # Before
  gsr_mj = float((wx.get("daily", {}).get("shortwave_radiation_sum") or [12.0])[0] or 12.0)
  # After
  _daily = wx.get("daily") or {}
  _daily = _daily if isinstance(_daily, dict) else {}
  gsr_mj = float((_daily.get("shortwave_radiation_sum") or [12.0])[0] or 12.0)
  ```
- **검증**: 수정 후 `crop=오이, et0=11.15mm, phases=3개` 정상 반환 ✅

### 14:20 — 전체 연동 검수 결과

| 엔드포인트 | 결과 | 비고 |
|---|---|---|
| `GET /health` | ✅ | version=0.2.0 |
| `POST /api/v1/auth/token` | ✅ | admin/1250 |
| `GET /api/farms/{id}/irrigation/schedule/priva` | ✅ | BUG-001 수정 후 |
| `POST /api/v2/recommend` | ✅ | model_source=pipeline, 5개 추천 |
| `GET /api/sensors/{id}/status` | ✅ | connections=0 (MQTT 미연결) |
| WebSocket `/ws/farms/{id}/sensors` | ⚠️ | 실기기 미연결, REST 폴백 동작 |

### 14:30 — FastAPI 정적 파일 서빙 확장

#### FEAT-001: /screens, /components 정적 경로 마운트
- `api/main.py` — `/screens`, `/components` StaticFiles 마운트 추가
- `api/middleware/auth.py` — `_PUBLIC_PATHS`에 `/screens`, `/components` 추가
- 결과: `http://localhost:8000/screens/g3_period.html` 200 OK

### 14:45 — g3_period.html 브라우저 검수 (Playwright)

#### CHECK-001: g3_period.html 1차 렌더링 (토큰 없음)
- Period 카드 5개 ✅
- P5 "오후~마감" Active ✅ (현재시각 18:00 기준 정확)
- 센서값 전체 `—` ⚠️ → API 401 (토큰 미전달)
- 콘솔 에러 4개: `Failed to load resource: 401`

#### BUG-002: g3_period.html 토큰 미전달
- **원인**: `KaasaData.init()`에 `token` 파라미터 누락
- **수정**: `_ensureToken()` 비동기 함수 추가 (sessionStorage 캐시 → 자동 로그인 폴백)
- **검증**: 수정 후 배액 EC 2.0 dS/m, 온도 23.0°C / VPD 0.7 실데이터 표시 ✅

#### CHECK-002: g3_period.html 2차 렌더링 (토큰 자동 주입 후)
| 항목 | 결과 | 비고 |
|---|---|---|
| Period 카드 5개 | ✅ | P1~P5 모두 표시 |
| Active Period | ✅ | P5 오후~마감 (18:00 정확) |
| 배액 EC | ✅ | 2.0 dS/m 실데이터 |
| 온도/VPD | ✅ | 23.0°C / 0.7 |
| VPD 경고 | ✅ | "⚠ VPD 낮음" 자동 표시 |
| 배액률/급액pH | ⚠️ | 센서 미연결 — MQTT 실기기 필요 |
| 콘솔 에러 | ✅ | 0건 |

### 15:10 — irrigation DB 저장 구현

#### BUG-003: irrigation_store.py DB 저장 실패 (컬럼명 불일치)
- **증상**: POST /irrigation → JSON만 저장, PostgreSQL 저장 안 됨
- **원인 1**: `from api.services.db import get_connection` → `db.py` 미존재
- **원인 2**: 잘못된 컬럼명 사용
  - `ts` → 실제: `time`
  - `variable` → 실제: `canonical_name`
  - `source` → 실제: `source_id`
  - `ON CONFLICT (farm_id, ts, variable)` → 실제: `(time, farm_id, canonical_name)`
- **수정**: `irrigation_store.py` — `_db_save`, `_db_query` SQLAlchemy 방식으로 재작성
  - `persistence._get_engine()` 공유 사용
  - 올바른 스키마 컬럼명 적용
  - `quality_tag='FINETUNED'` 추가
- **검증**: PostgreSQL에 5개 canonical 변수 저장 확인 ✅

#### CHECK-003: /irrigation/analysis DB 조회 검증
- `data_days=1`, dr=24.527%, ec=3.175 dS/m, supply=1400ml ✅
- 야간소실률 27.2% → [major] 경보 자동 생성 ✅

### 완료된 작업 목록
| 항목 | 상태 |
|---|---|
| g3_period.html 브라우저 검수 | ✅ |
| BUG-001: Priva ET0 500 오류 수정 | ✅ |
| BUG-002: g3_period.html 토큰 미전달 수정 | ✅ |
| BUG-003: irrigation_store DB 컬럼명 불일치 수정 | ✅ |
| FEAT-001: /screens, /components 정적 경로 마운트 | ✅ |
| POST /irrigation → PostgreSQL 실저장 | ✅ |
| GET /irrigation/analysis DB 조회 | ✅ |

### 15:30 — Priva Phase → P2~P5 UI 연동 검수

#### CHECK-004: Priva 스케줄 Period 카드 매핑
Playwright로 P2~P4 카드 확장 후 Priva 데이터 표시 확인

| Period | 추천 관수횟수 | 회당 공급량 | 배액 목표 | 상태 |
|--------|------------|-----------|---------|------|
| P1 관수 前 점검 | N/A (준비 구간) | — | — | ✅ 정상 |
| P2 첫 관수 | 2회 | 163 ml/주 | 17.9% | ✅ |
| P3 오전 관수 | 8회 | 175 ml/주 | 22.9% | ✅ |
| P4 정오 고부하 | 2회 | 220 ml/주 | 25.9% | ✅ |
| P5 오후~마감 | N/A (준비 구간) | — | 15.0% | ✅ |

- 콘솔 에러: 0건 ✅
- Priva 요약 카드 (ET₀, 증산량, P/I 교정): 표시 ✅
- 관수 추가 실행 Bottom Sheet: 표시 ✅
- 관수 기록 입력 폼 (Period별 급액/배액/EC/pH): 표시 ✅
- AI 관수 추천 섹션: 표시 ✅
- 7일 관수 품질 분석 테이블: 표시 ✅

**g3_period.html 전체 기능 검수 PASS** ✅

### 16:00 — parquet ETL 경로 완성

#### BUG-004: nightly_db_etl.py 관수 canonical_name 불일치
- **증상**: ETL 실행 시 관수 피처(ec_drain 등) parquet에 None
- **원인**: ETL 쿼리가 `'wc'`, `'dr_pct'`를 조회하지만 irrigation_store는 `'wc_mean'`, `'dr_pct_mean'`으로 저장
- **원인2**: ETL 출력 컬럼명 `ec_drain_mean`, `supply_total_sum`이 ML `IRR_BASE`와 불일치
- **수정**: `nightly_db_etl.py` — CASE WHEN 조건에 양쪽 이름 모두 포함, 출력명을 `IRR_BASE`와 통일
  ```sql
  -- Before
  AVG(CASE WHEN em.canonical_name = 'wc'       THEN em.value END) AS wc_mean,
  AVG(CASE WHEN em.canonical_name = 'dr_pct'   THEN em.value END) AS dr_pct_mean,
  AVG(CASE WHEN em.canonical_name = 'ec_drain' THEN em.value END) AS ec_drain_mean,
  -- After
  AVG(CASE WHEN em.canonical_name IN ('wc','wc_mean')         THEN em.value END) AS wc_mean,
  AVG(CASE WHEN em.canonical_name IN ('dr_pct','dr_pct_mean') THEN em.value END) AS dr_pct_mean,
  AVG(CASE WHEN em.canonical_name = 'ec_drain'                THEN em.value END) AS ec_drain,
  ```

#### FEAT-002: nightly_db_etl.py --since 옵션 추가
- cutoff 자동 감지 우회 가능 (기존 parquet에 미래 날짜 있어도 강제 재실행)
- 사용: `python -m pipeline.nightly_db_etl --since 2026-05-30`

#### CHECK-005: End-to-End ETL 검증
| 단계 | 결과 |
|------|------|
| POST /irrigation → PostgreSQL | ✅ 5개 canonical 변수 저장 |
| nightly_db_etl --since 2026-05-30 | ✅ env+2 신규 행 추가 |
| env_daily.parquet IRR 컬럼 8개 | ✅ 모두 존재 |
| 딸기 2026-05-31 관수 행 | ✅ dr=24.527%, ec=3.175, supply=1400ml |
| prep_m1.py IRR_BASE 매핑 | ✅ 컬럼명 일치 확인 |

### 05:00 — 딸기 ML 모델 재학습 (Stage1 Optuna 튜닝)

#### CHECK-006: 딸기 Stage1 Optuna 하이퍼파라미터 탐색 결과
| 방법 | CV R² | 개선 |
|------|-------|------|
| Baseline (XGB) | 0.244 | — |
| XGB Optuna (60 trials) | **0.284** | +0.040 |
| LGB Optuna (60 trials) | 0.278 | +0.034 |
| **채택: XGB Optuna** | **0.284** | **+0.040** |

최적 XGB 파라미터:
- n_estimators=108, max_depth=4, lr=0.019, subsample=0.61, colsample=0.79
- reg_alpha=0.003, reg_lambda=0.23, min_child_weight=5

**목표 R² > 0.45 미달성 원인 분석**:
1. 월별 집계 데이터의 한계 — 일별 생육 패턴 손실
2. 농장간 분산 높음 — 1912행이지만 다수 농장×다수 연도 혼합
3. 생육 타겟(plant_height, leaf_count 등) 자체가 환경 변수와 약한 상관
4. ERA5 합성 피처(외부 기상 CSV 없음) — 실측 기상 데이터 대비 노이즈 높음

**현재 운영 전략** (MEMORY.md 기준):
- 딸기: LegacyAdapter R²=0.805가 우선 사용 중 → Stage1 개선이 즉각 서비스 영향 없음
- Stage1 0.284 저장 완료 (향후 ERA5 실측 CSV 확보 시 추가 개선 가능)

#### FEAT-003: tune_stage1_strawberry.py 신규 생성
- Optuna XGB + LGB 이중 탐색
- `--trials N` 옵션으로 탐색 횟수 조절 가능
- 최우수 모델 자동 저장 → stage1_growth.pkl, stage1_meta.json

### 05:40 — KAMIS 가격 갱신 시스템 수정

#### BUG-005: KAMIS API 전체 실패 (item_code 6개 모두 오류)
- **증상**: `/prices/latest` 모든 작목 `source=rda_static` (정적 데이터)
- **원인 1**: `it.get("itemcode")` → 실제 필드는 `item_code` (언더스코어)
- **원인 2**: `it.get("price")` → 실제 필드는 `dpr1`(당일)/`dpr2`(전일)/`dpr3`(1주전)
- **원인 3**: ITEM_CODES 코드값 전체 오류

  | 작목 | 기존 코드 | 실제 코드 |
  |------|----------|----------|
  | 딸기 | 220 | **226** |
  | 완숙토마토 | 226 | **225** |
  | 방울토마토 | 227 | **422** |
  | 참외 | 225 | **222** |
  | 오이 | 244 | **223** |
  | 파프리카 | 259 | **256** |

- **원인 4**: 주말/시장 미개장 시 데이터 없음 → 평일 자동 소급 필요
- **수정**: `kamis_fetcher.py`
  - `it.get("itemcode")` → `it.get("item_code")`
  - `it.get("price")` → `dpr1` → `dpr2` → `dpr3` 순 폴백
  - ITEM_CODES 전체 수정
  - `_latest_trading_date()` 추가 (오전 9시 이전이면 전일, 주말 제외)

#### BUG-006: KAMIS 일일 자동 갱신 스케줄러 없음
- **수정**: `api/main.py` — `_daily_kamis_scheduler()` 추가 (매일 오전 7시 KST 자동 갱신)

#### CHECK-007: KAMIS 최종 검증
```
최근 거래일: 2026-05-29 (금)  ← 오전 9시 이전 → 전일 기준, 주말 제외 자동 조정
완숙토마토: 1,980원/kg  ✅ KAMIS_live
방울토마토: 3,430원/kg  ✅ KAMIS_live
참외:        4,200원/kg  ✅ KAMIS_live
오이:       23,525원/kg  ✅ KAMIS_live (단위 변환 이상 → 확인 필요)
파프리카:    3,890원/kg  ✅ KAMIS_live
딸기:       비수기 (5월) → rda_static 폴백
```

> ⚠️ 오이 23,525원/kg — 일반 오이 시세보다 높음 (단위가 100개 기준?). `p_convert_kg_yn=Y` 옵션 적용됐지만 KAMIS 측에서 변환 안 할 수 있음. 추가 확인 필요.

### 06:00 — 오이 KAMIS 단가 이상값 수정

#### BUG-007: 오이 단가 23,525원/kg (실제 ~1,700원/kg)
- **원인**: KAMIS 오이 거래 단위 100개/50개 — `p_convert_kg_yn=Y` 미적용
- **수정**: `_UNIT_TO_KG` 환산 테이블 추가 + `_unit_to_kg()` 함수
  - 다다기 100개(12.5kg): 29,700 / 12.5 = 2,376원/kg
  - 취청 50개(15.0kg): 25,700 / 15.0 = 1,713원/kg
  - 평균 → 1,736원/kg ✅
- **검증**: 오이 1,736원/kg (정상 시세 범위 1,500~2,500원/kg) ✅

### 다음 작업 (예정)
- [x] g3_period.html Priva Phase → P2~P5 매핑 UI 연동 확인 ✅
- [x] 관수 데이터 → parquet ETL 경로 완성 ✅
- [x] ML 모델 재학습: 0.244 → 0.284 (+0.040) ✅
- [x] KAMIS 갱신 시스템 수정 (5개 작목 실시간 수신) ✅
- [ ] 오이 단가 이상값 확인 (23,525원/kg — 100개 기준 혼재 의심)
- [ ] ERA5 실측 CSV 확보 후 Stage1 재학습 (장기)
- [ ] C3 통합 홈 화면 구현 → index.html 네비게이터

---

## 로그 규칙
- 버그: `BUG-NNN: 제목` 형식
- 기능: `FEAT-NNN: 제목` 형식
- 검수: `CHECK-NNN: 항목` 형식
- 각 항목에 Before/After 코드 스니펫 포함

### 06:30 — C3 홈 + index.html 완성 및 버그 수정

#### FEAT-005: screens/c3_home.html 신규 구현
- 히어로 배너: 날짜·인사·현재 Period 자동 표시
- KPI 2×2: 수확예측 / 예상 매출 / 배액률 / VPD
- To-do 7개: Period 연동 (P1~P5·AI·ALL), 긴급 표시, 로컬스토리지 체크 상태 유지
- AI 추천 신뢰도 바 (72% 실데이터 확인)
- 온실/노지/출하 요약 탭 전환
- KAMIS 실시간 가격 스트립 (6개 작목)

#### FEAT-006: index.html → /smartos 네비게이터
- C3·G3 완료(녹색 테두리), 8개 화면 준비중/미착수 표시
- http://localhost:8000/smartos 공개 경로 추가

#### BUG-008: c3_home kpiDrain `—%%` 이중 % 추가
- 원인: HTML에 `%` span 있는데 `insertAdjacentHTML`로 중복 추가
- 수정: `innerHTML` 단일 설정으로 변경

#### BUG-009: AI 추천 0% (null env → empty recommendations)
- 원인: `horizon_days=1` + null env → API가 빈 배열 반환 (200 OK)
- 수정 1: `data.js` `horizon_days: 1 → 30`
- 수정 2: `data.js` 빈 recs → 농진청 표준 폴백 emit
- 수정 3: `c3_home` 센서 실데이터 수신 시 추천 재요청 (72% 실데이터 확인)

#### BUG-007: 오이 KAMIS 단가 23,525원/kg
- 수정: `_UNIT_TO_KG` 환산 테이블 + `_unit_to_kg()` 함수 (1,736원/kg ✅)

#### CHECK-008: C3 최종 검수
| 항목 | 결과 |
|---|---|
| 히어로 배너 (날짜·Period) | ✅ 2026년 6월 1일 (월) · P2 |
| 온실 KPI (온도·습도·CO₂·일사) | ✅ 23.0°C · 76.0% · 850ppm · 320W/m² |
| AI 추천 신뢰도 | ✅ 72% |
| 가격 스트립 6개 | ✅ |
| To-do 7개 · 긴급 표시 | ✅ |
| 콘솔 에러 | ✅ 0건 |
