# KAASA smartfarmingsight — 작업 메모리
> 세션 시작 시: NEXT.md만 읽을 것. 이 파일은 아키텍처 변경 시만 참조.
> 세션 기록은 archive/SESSIONS_2026-06.md로 이관 완료.

---

## 브랜드 & 운영

- **제품명**: KAASA smartfarmingsight
- **도메인**: https://farmingsight.org (Cloudflare Named Tunnel, kaasa-smartos)
- **서버**: `PYTHONPATH=C:\smart_farm PUBLIC_DEMO=1 python -m uvicorn api.main:app --port 8000`
- **터널**: `cloudflared tunnel --config deploy/cloudflare/config.yml run kaasa-smartos`
- **SW 캐시**: 현재 v16 — 화면 변경 시 반드시 bump (base.css 또는 data.js CACHE_VERSION)
- **감시**: `deploy/cloudflare/watchdog.ps1` 30초 주기 자동재기동 (Mutex 단일인스턴스 가드)

## 영구 제약 (위반 시 서비스 장애)

- `PUBLIC_DEMO=1` 환경에서 `/api/admin/*` 전부 403 (notify·drift·retrain 포함)
- 쓰기 허용 경로만 선별 개방 (`api/main.py` `_WRITE_ALLOW*` 3개 상수)
- 기능식별자 `/smartos`·터널명 `kaasa-smartos`·SW키는 브랜드 치환 대상 제외
- `SMTP_USER`·`SMTP_PASSWORD`·`ANTHROPIC_API_KEY` → .env 미설정 시 폴백 동작

## 현재 구현 상태

- **화면**: 41개 (screens/), 네비게이터 index.html
- **라우터**: api/routers/ (farmer·admin·auth·federated 등)
- **작물**: 온실 6종 + 제주노지 7종 = 13종
- **모델**: M2 딸기(R²0.295·PASS)·오이·완숙·파프리카(PASS) / 방울(48.6%·FAIL)·참외(63.9%·FAIL)→폴백

## 핵심 아키텍처

```
screens/         ← 모바일 HTML 41화면
components/
  base.css       ← CSS 변수, 팔레트 토큰 --chart-hot/cool/good/warn/rain
  data.js        ← 전역 레이어: _DEMO_FARMS·_installFab·toggleTheme·RecordSheet
api/
  main.py        ← FastAPI, PUBLIC_DEMO 게이트, 스케줄러
  routers/       ← farmer·admin·auth·federated
  services/      ← climate_plan·consulting_diagnosis·capability_router·climatology
  data/          ← farm_registry·diagnosis·equipment·real/*.json
models/          ← registry.json, artifacts/{crop}/
pipeline/        ← state/retrain_history·new_rows_since_retrain
deploy/cloudflare/ ← config.yml·watchdog.ps1
```

## ★ P1~P6 관수 Period 정의 (Priva/Grodan 기반 — 절대 변경 금지)

| Period | 시간대 | 핵심 지표 |
|--------|--------|-----------|
| P1 | 일출 전 (05:00~07:00) | EC/pH 기준값, 야간 dry-back 10~20% |
| P2 | 첫 관수·재포화 (일출+2~3h) | 급액량 슬랩 4~6%, 배액 前 |
| P3 | 오전 첫 배액 (≈400 J/cm²) | 배액률 20~30%, VPD |
| P4 | 정오 고부하 (12:00~15:00) | 함수율 64~65%, 12%↓ 즉시추가 |
| P5 | 오후 dry-down (15:00~일몰) | dry-back 2~5%, EC 상향 |
| P6 | 야간 dry-back (일몰~05:00) | dry-back 10~20%, 무관수 기본 |

**트리거: 일사 적산(J/cm²) 우선, 시각은 폴백**

## G3 센서 정상 범위

| 항목 | 단위 | 정상 | 경보 |
|------|------|------|------|
| 급액 EC | dS/m | 2.5~3.5 | >4.0 또는 <2.0 |
| 배액 EC | dS/m | 3.0~4.5 | >5.0 |
| 배액률 | % | 20~30 | <15 또는 >40 |
| 급액 pH | — | 5.5~6.5 | <5.0 또는 >7.0 |

## 핵심 KPI 기준값 (PC↔모바일 통일값)

- DLI: PAR계수 4.57 mol/m²·d 사용 (누락 시 ~4.6배 과소 오류)
- VPD 밴드: 0.4 kPa (하한) / 0.6 kPa (상한)
- 배액률 정상: norm[20, 35]% / 위험: crit[15, 45]%

## G2 환경관리 전략표 (climate_plan.py)

- 2축: 행=생육시기(정식기준) × 열=하루4구간(야간·일출·주간·일몰전)
- 셀=온도/습도/CO₂ (VPD 자동 계산)
- 벤치마크: Priva 광연동승온 / HNT 24h평균 / Plant Empowerment VPD밴드
- `evaluate()`: 전략표 목표 대비 실측편차 → AI 처방 생성

## 검수 기준

- 터치 타겟 48px 이상 (장갑 낀 손 기준)
- 첫 화면 LCP < 3.0s (Slow 3G)
- 콘솔 에러 0 / API 4xx 0 / 깨진 링크 0 전 화면

## 사용자 조치 필요 (내가 못함)

- **SMTP**: `.env` `SMTP_USER`·`SMTP_PASSWORD` 미설정 (Gmail 앱비번 16자 필요)
- **LLM**: `ANTHROPIC_API_KEY` 미설정 → 챗봇 규칙 기반 폴백
- **터널 영속**: `cloudflared service install` (관리자 권한 선택사항)
