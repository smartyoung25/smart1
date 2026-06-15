# 보안 조치 수행 결과 (P0 핫픽스) — KAASA smartfarmingsight

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

## 명시적 이연 (다음 라운드)
- **P1**: A1 fail-closed(JWT 미설정 기동거부) — `.env` 존재로 운영 위험 낮음.
- **P2**: B1 무료 enterprise 승급 / I3 연합 factor clip / Z6 billing overview 권한 — `¬PUBLIC_DEMO` 전제라 데모에서 미성립(POST 차단).
- **P3**: P1 클러스터 PII 최소화 / `dashboard/` 죽은코드 archive 이동(autologin.html 포함) / README–실제 배포 문서 일치 / Z2 UUID 전면 마이그레이션.

## 핵심 변경 파일
- `api/routers/data_collection.py` · `api/routers/ws.py` · `api/routers/auth.py` · `api/routers/farmer.py`
- `api/middleware/auth.py`(_PUBLIC_PATHS·require_admin_view) · `api/main.py`(_WRITE_ALLOW) · `api/services/persistence.py`
- `components/data.js`(WS 토큰) · `screens/*.html`×39+`dashboard/*`(데모토큰 전환) · `sw.js`(v35)
