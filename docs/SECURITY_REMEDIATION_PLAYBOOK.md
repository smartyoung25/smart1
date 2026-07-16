# 보안 조치 수행 결과 (P0 핫픽스) — KAASA Farmingsight

> 대상: 운영 `C:\smart_farm` (D2 배포 — Cloudflare tunnel `kaasa-smartos` → uvicorn :8000, PUBLIC_DEMO=1)
> 근거: 외부 코드분석 보고서(리뷰 사본 `E:\…\smart1`) + 운영 코드 실재성 교차검증(Explore ×3)
> 수행일: 2026-06-15 · 브랜치 `security-remediation` → 페이즈별 master 머지

## 수행 요약 (P0 — 운영(PUBLIC_DEMO=1)에서도 성립하는 실재 위험)

| 페이즈 | 취약점 | 조치 | 커밋 |
|--------|--------|------|------|
| A | I1 무인증 모델오염 / I2 재학습 DoS / I4 이력 IDOR | `/api/data/*` require_auth + farm_id 소유권 + 재학습 데모 시뮬레이션화(subprocess 차단). `_PUBLIC_PATHS`에서 `/api/data` 제거 | `5a1e39e` |
| B | Z4 WS 무인증 도청 / Z5 센서 IDOR | `/ws/farms/{id}/sensors` ?token= 검증+소유권(close 4401/4403). `/api/sensors/*` require_auth+소유권. data.js WS 토큰 부착 | `c998dc4` |
| C | A2 admin/1250 하드코딩(39+파일) | 무자격 `POST /api/v1/auth/demo-token`(PUBLIC_DEMO 전용) 신설 → 42파일 자격증명 제거. `require_admin_view`로 데모 관리자 조회 유지, 파괴작업은 미들웨어 차단 | `e28e66b` |
| D | Z1 빈 farm_id 우회 / Z2 username→농가탈취 / Z3 farm_001 보정 | farmer 소유권 빈값 거부 / 신규가입 farm_id 고유화(`farm_u`+hex) / farm_001 자동보정 제거 | `4c764cb` |

## 보안 재현 차단 검증 (8/8 PASS)
- I1 무토큰 `/api/data/harvest` POST → 401
- I4 무토큰 `/api/data/growth` GET → 401
- Z5 무토큰 `/api/sensors/{id}/latest` → 401
- Z4 무토큰 WS `/ws/farms/{id}/sensors` → 거부
- A2 소스 내 `admin/1250` 자격증명 → 0건, demo-token 발급 200
- demo 토큰: 관리자 조회 200 / 파괴 promote 403 / 데이터 소유권 200
- Z2 username `001` 가입 → farm_id=`farm_u…`(≠farm_001), farm_001 접근 403

## 기능 회귀 (없음)
- 핵심 화면 17종 + smartos/intro 라우트 200, 콘솔/4xx 0
- 데모 다농장(farm_001~005) 전환 시연 정상(demo 역할 소유권 바이패스)
- G3 관수 기록·G4 생육·G5 방제 기록 등 데모 쓰기 정상(demo 토큰 보유)

## 추가 완료 라운드

**P1 + P3** (커밋 `a7826b8`):
- A1 fail-closed: JWT 라이브러리/시크릿 미설정 시 익명 통과 → 401 거부(`middleware/auth.py`).
- dashboard 죽은코드 `archive/dashboard/` 이관 + main.py 루트 라우트 디커플 + README/docker-compose 정정.

**P2 결제·연합 무결성** (이번 라운드):
- **B1** `billing.py request_upgrade`: 농장 소유권 검증 추가 + 클라이언트 `pg_channel="manual"` 즉시승인을 **관리자 전용**으로 제한(일반 사용자는 결제채널만 → 콜백 전 티어 미변경). billing GET(plan/quota/features)에도 소유권 적용.
- **Z6** `billing.py admin_billing_overview`: `require_auth` → `require_admin_view`(일반 사용자 403, 데모 조회 허용).
- **I3** `aggregate.py merge_corrections`: factor[0.5,2.0]·shrink[0,1]·n≥0 클램프(추론 오염 차단). `federated.py post_correction`: require_auth + 업로드 farm_id를 토큰 농장으로 바인딩(타농장 보정 덮어쓰기 403).
- 검증(비데모 8001): B1/Z6/I3 인증·소유권 10/10 PASS, factor 클립 단위검증, 데모 회귀 0(GET 200·POST 게이트 403 유지).

## 명시적 이연 (잔여)
- **P3 잔여**: P1 클러스터 PII 최소화(무인증 farm_id·지역 노출) / Z2 UUID 전면 마이그레이션(현재 신규가입만 고유화) / watchdog abandoned-mutex 중복기동 가드.

## 핵심 변경 파일
- `api/routers/data_collection.py` · `api/routers/ws.py` · `api/routers/auth.py` · `api/routers/farmer.py`
- `api/middleware/auth.py`(_PUBLIC_PATHS·require_admin_view) · `api/main.py`(_WRITE_ALLOW) · `api/services/persistence.py`
- `components/data.js`(WS 토큰) · `screens/*.html`×39+`dashboard/*`(데모토큰 전환) · `sw.js`(v35)
