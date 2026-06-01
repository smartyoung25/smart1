# KAASA SmartOS — 작업 메모리 (CLAUDE.md)
> 매 세션 시작 시 이 파일을 반드시 먼저 읽을 것.
> 매 세션 종료 시 결정사항·진행상태·남은 일을 반드시 이 파일에 기록할 것.

---

## ★ 핵심 재정의 (2026-05-31 확정)

### P1~P6은 하루 관수 Period (Priority가 아님) — Grodan/Priva 일일 WC·EC 곡선 기반
| Period | 시간대 | 의미 | 핵심 지표 |
|--------|--------|------|-----------|
| P1 | 일출 전 (05:00~07:00) | 야간 dry-back 확인·첫 관수 산정 | EC/pH 기준값, 야간 dry-back 10~20% |
| P2 | 첫 관수·재포화 (일출 후 2~3h) | 큰 급액으로 염류 세척·EC↓ | 급액량 슬랩 4~6%, 첫 배액 前 |
| P3 | 오전 첫 배액 (≈400 J/cm²) | 최고 일사대에서 배액 EC 최저 | 배액률 20~30%, VPD |
| P4 | 정오 고부하·유지 (12:00~15:00) | 함수율 64~65% 유지 | 배액률 20~30%(고EC 25~50% 세척), 12%↓ 즉시추가 |
| P5 | 오후 dry-down (15:00~일몰) | 조기 종료·생식생장 유도 | 일몰까지 dry-back 2~5%, EC 상향 |
| P6 | 야간 dry-back (일몰~05:00) | 생식/영양 조절·뿌리 산소화 | dry-back 10~20%, 배액 0%, EC 상향(무관수 기본) |

**트리거는 일사 적산(J/cm²) 우선·시각은 폴백. 작업지시서의 P1/P2/P3 우선순위 표기는 전면 폐기.**
**(2026-06-02) P6 야간 dry-back 추가 — `components/data.js` PERIODS, getCurrentPeriod(야간 분기), base.css --p6-*, g3 jump-btn 셀렉터. 6화면 회귀 에러0.**

---

## 프로젝트 개요

- **프로젝트명**: KAASA SmartOS 모바일 최적화 + 데이터 연동 구현
- **목표**: 온실 농가가 스마트폰으로 P1~P5 관수 Period를 실시간 관리하고, AI 추천을 즉시 실행할 수 있는 모바일 퍼스트 시스템
- **기준 파일**: kaasa_smartos_wireframe_html.html (원본 와이어프레임)
- **산출물 위치**: C:\smart_farm\

---

## 핵심 아키텍처 결정

### 1. 산출물 구조 (단일 파일 → 분리 구조)
```
C:\smart_farm\
├── CLAUDE.md          ← 이 파일 (작업 메모리)
├── PROGRESS.md        ← 화면별 진행 상태
├── index.html         ← 전체 화면 네비게이터
├── components/
│   ├── base.css       ← CSS 변수, 공통 스타일
│   ├── components.css ← 컴포넌트 클래스 (KPI, To-do, Bottom Sheet 등)
│   └── data.js        ← 데이터 연동 레이어 (API 모킹 + 실제 연동 준비)
├── screens/
│   ├── g3_period.html ← ★ 핵심: P1~P5 관수 Period 관리 (최우선)
│   ├── c3_home.html   ← 통합 홈 (To-do 중심)
│   ├── g2_env.html    ← 환경제어
│   └── ...
└── releases/
    └── v*.zip
```

### 2. 데이터 연동 레이어 (3단계)
```
[센서/API 원천] → [data.js 연동 레이어] → [화면 렌더링]
     ↑                    ↑                      ↑
  실제 연동 시          Mock → Real 전환          Period 상태
  교체 가능             점진적 연동               시각화
```

### 3. 모델 연계 구조
- **Layer 0**: 농진청 표준모델 (정적 기준값 — JSON 파일로 제공)
- **Layer 1**: KAASA 현장학습모델 (API 호출 → 추천값 반환)
- **Layer 2**: 내 농장 맞춤모델 (농장별 보정 파라미터 적용)
- **data.js**가 이 3개 레이어를 순서대로 폴백(fallback) 처리

---

## G3 관수·양액 Period — 데이터 스펙

### 센서 데이터 (실시간)
| 항목 | 단위 | 정상 범위 | 경보 기준 |
|------|------|-----------|-----------|
| 급액 EC | dS/m | 2.5~3.5 | >4.0 또는 <2.0 |
| 배액 EC | dS/m | 3.0~4.5 | >5.0 |
| 배액률 | % | 20~30% | <15% (부족), >40% (과잉) |
| 급액 pH | — | 5.5~6.5 | <5.0 또는 >7.0 |
| 급액량 | mL/주 | Period별 상이 | 농장 기준값 ±20% |

### AI 모델 추천 입력값
- 현재 Period (P1~P5)
- 배액률 현재값
- 누적 DLI (일사량 누적)
- 실외 VPD 예측값
- 전일 수확량 대비 현재 생육단계

### AI 추천 출력값
- 추가 관수 여부 (boolean)
- 추천 급액량 (mL/주)
- 추천 EC 조정값 (dS/m)
- 신뢰도 점수 (0~100%)
- 추천 근거 (텍스트, max 50자)

---

## 검수 기준 (Verification Criteria)

### 1. 정확성 (Accuracy)
- AI 추천값이 농진청 표준모델 기준 ±15% 이내인지
- Period별 배액률 계산이 센서값과 일치하는지
- 경보 임계값이 설정값과 정확히 연동되는지
- 데이터 갱신 주기: 실시간(5초) / 집계(1분) / 일간(자정)

### 2. 사용성 (Usability)
- 온실 현장에서 장갑 낀 손으로 조작 가능한지 (터치 타겟 48px 이상)
- 현재 Period(P1~P5) 상태를 3초 이내에 파악할 수 있는지
- AI 추천 → 실행 → 결과 확인이 3탭 이내로 가능한지
- 에러/경보 상태가 색맹 사용자에게도 명확한지 (색상 + 아이콘 + 텍스트 3중 표현)

### 3. 효율성 (Efficiency)
- 첫 화면 로딩 3초 이내 (LCP < 3.0s, Slow 3G 기준)
- Period 전환 시 화면 갱신 1초 이내
- 관수 적용 버튼 → 실행 피드백 0.5초 이내
- 하루 관수 의사결정(P1~P5)에 소요되는 총 화면 조작 시간 < 2분

### 4. 효과성 (Effectiveness)
- 배액률 목표(20~30%) 달성 여부를 화면에서 즉시 확인 가능한지
- AI 추천 수용률 추적 (수용 vs 거부 비율 기록)
- Period별 실제 적용값 vs 추천값 편차 추적
- 농진청 표준 대비 내 농장 모델 정확도 비교 가능한지

---

## 결정 로그 (Decision Log)

| 날짜 | 결정 | 근거 | 결정자 |
|------|------|------|--------|
| 2026-05-31 | P1~P5를 관수 Period로 재정의 | 사용자 지시 | 사용자 |
| 2026-05-31 | 단일 HTML → 화면별 분리 | 컨텍스트 효율, 유지보수 | Claude |
| 2026-05-31 | data.js Mock → Real 전환 방식 | 점진적 연동 가능 | Claude |
| 2026-05-31 | G3 Period 화면을 최우선 구현 | 핵심 업무 빈도 최고 | 합의 |
| 2026-06-01 | 등급(티어) 차등 3계층 구현 | basic/smart/pro/enterprise SaaS 모델 | 합의 |
| 2026-06-01 | 글로벌 의사결정 UI 벤치마킹 → DecisionDeck | Priva·CropX·Source.ag 등 Top12 패턴 | 합의 |

## 등급 차등 & 의사결정 UI (2026-06-01)

### 등급 차등 (tier_features.json 기반)
- 레벨① index.html 맞춤메뉴+핵심그리드 잠금/배지 + 현재등급 칩
- 레벨② `components/tier_guard.js` 위젯 오버레이 — g2(VPD)·g3(드레인EC)·g4(수확예측)·g5(병해상세)·c5(이익률)·g6(AI출하)
- 레벨③ /billing/* + 402 게이팅 (백엔드 기존)
- 업그레이드 시트 → POST /billing/upgrade(manual) 실연동
- 검수: basic 잠금↑ / pro 해제, 콘솔 에러 0건

### DecisionDeck (글로벌 벤치마킹 적용)
- `components/decision_card.{css,js}` — `DecisionDeck.render(el, items, {onApply})`
- C3 홈 "오늘의 결정": 이상감지(배액률·VPD)+AI추천 통합, 심각도3중코딩+처방+신뢰도+출처+신선도+원탭(→/activity 폐루프)
- 벤치마킹 정리: `docs/UI_BENCHMARK.md`

### 벤치마크 Top12 전부 적용 (2026-06-01 2차)
- DecisionDeck → g1·f1 확장 (빌더 buildGreenhouse/buildField)
- `band_chart.js`(의존성0 SVG): g3 배액률 목표대 밴드 음영 (패턴6)
- `device_alert.js`: c3·g2 기기/연결 알림을 데이터 알림과 분리 (패턴12)
- F2 GIS: peelable 레이어 토글(필지경계/토양수분/NDVI) + 값 히트맵 (패턴7·8)
- 전 화면(10) 콘솔 에러 0건 회귀검수 통과

## 운영 기록 입력 + 기자재 통합 (2026-06-02)

### 운영 기록 폐루프 (RecordSheet)
- `components/record_sheet.js`: RecordSheet.open/logActivity/renderRecent
- 입력 화면: F4(관개)·F6(방제)·F7(필지수확)·G2(환경설정)·G3(관수)·G4(생육측정)·F3(작업계획) → POST /activity
- 각 화면 '최근 기록' 타임라인 (GET /activity/summary recent[])
- C4(전문가 consult)·C12(공동출하 joint_ship+물량/등급)·C2(consent) 실제 서버 적재
- C14 월간리포트: 이행 활동 상세(by_kind 칩)+최근기록 + 학습기여 재학습 트리거 연동(remaining_rows·near_retrain 배지)

### 시설 기자재 + 이기종 통합 (C16 신규)
- `docs/EQUIPMENT_INTEGRATION.md` + `api/data/equipment_schema.json`(8군·프로토콜·표준변수22)
- `screens/c16_equipment.html`: 장비 등록 + 데이터포인트→canonical_name 매핑
- 백엔드: GET /equipment/schema·GET/POST/DELETE /equipment (data/equipment/{farm}.json)
- C1 저장 후 CTA로 C16 연결 / `equipment_link.js`로 G2·G3에 '연동 장비' 배지 + device_alert 연계
- 전 32화면 콘솔 에러 0건 회귀검수 통과

---

## 완료된 화면 (2026-06-01 — 원본 28개 100% 완성)

| 모듈 | 화면 | 실연동 여부 |
|------|------|-----------|
| 공통 C (13) | C0 C1 C2 C3 C4 C5 C6 C7 C8 C9 C10 C11 C12 | C3·C4·C5·C6·C12 실연동, 나머지 auth/Mock |
| 온실 G (6) | G1 G2 G3 G4 G5 G6 | 전부 실연동 |
| 노지 F (7) | F1 F2 F3 F4 F5 F6 F7 | F1·F3·F4·F6·F7 실연동, F2·F5 Mock |
| 개요 (2) | overview.html, flow.html | 정적 |
| 네비게이터 | index.html → /smartos | 28화면 완료 배지 |

- 전 화면 **표준 하단 5탭**(홈/온실/노지/출하/메뉴) 통일 · 죽은 링크 0건 · 콘솔 에러 0건
- 표준 템플릿: `_ensureToken()` 자동로그인(admin/1250) + `KaasaData` 레이어 + Playwright 검수
- Mock 부분은 화면에 라벨 명시 (노지 토양수분·필지 GIS·원격탐사, C6~C10 일부)

## 백엔드 수정 누적 (2026-06-01)

- `api/services/irrigation_store.py` — DB 컬럼명 수정, PostgreSQL 실저장
- `api/routers/farmer.py` — Priva ET0 500 버그 수정
- `api/main.py` — /screens /components 마운트, KAMIS 일일 스케줄러
- `api/middleware/auth.py` — /screens /components /smartos 공개
- `pipeline/nightly_db_etl.py` — IRR canonical_name + --since 옵션
- `pipeline/kamis_fetcher.py` — ITEM_CODE 전면 수정 + 단위 환산 + 평일 소급
- `components/data.js` — horizon_days 30, 빈 recs 폴백, 농진청표준 강화
- `scripts/tune_stage1_strawberry.py` — Optuna (R² 0.244→0.284)

## 다음 세션 작업 (우선순위)

- [ ] C12 공동출하 화면 구현
- [ ] Lighthouse LCP < 3.0s 검수
- [ ] 실기기 QR 테스트 환경 구성
- [ ] ERA5 실측 CSV 확보 → 딸기 Stage1 재학습 (R² > 0.45)
- [ ] KAMIS 딸기 비수기 → 성수기 전환 시 단가 자동 반영 확인

## 미해결 Backlog

- [ ] KAASA 실제 API 엔드포인트 확인
- [ ] 농진청 표준모델 JSON 수신 방법
- [ ] 실기기 MQTT 연결 테스트
- [ ] kaasa_smartos_mobile.html (90KB 단일 파일) → 분리 작업 계획

---

## 다음 세션 시작 메시지 템플릿

```
CLAUDE.md를 읽고 시작합니다.
오늘 목표: [화면명] 완성
현재 상태: PROGRESS.md [해당 항목] 참조
주의사항: [특이사항]
```


## 최종 구현 현황 (2026-06-01)

### 화면 33개 (원본 28 + AI챗봇·월간리포트·교육·기타)
- 공통 C: C0~C12 + c13(AI챗봇) + c14(월간리포트) + c15(교육)
- 온실 G: G1~G6 / 노지 F: F1~F7 / 개요: overview·flow

### 작물 12종
딸기·방울토마토·완숙토마토·참외·파프리카·오이 + 제주7종(감귤·월동무·당근·양배추·브로콜리·마늘·양파)

### 정책(스마트농업법) 대응 — 기능 이행 완료
- 6대 영역 통합 모니터링 / 9대 성과지표(목표대비+전월대비 변화율)
- 월간 경영성과 리포트(제5·6·9조) / 교육과정·이수율(제8조)
- 결로·IPM 조기경보 / AI진단·전문가 컨설팅(C4)
- **이행→축적→학습→환원 폐루프**: activity 적재→retrain_trigger→report 학습블록→C7 보상

### 외부 의존 잔여 (코드 구조 완비, 키/데이터만 주입하면 자동 전환)
- 노지 토양·필지·NDVI 실데이터(흙토람·팜맵 키+IP) / LLM 챗봇 실응답(.env 키)
- 제주작물 M2 수확모델(생산 실측) / 전월 변화율 실수치(월 누적)

### 신규 백엔드 (이번 세션)
- GET /report/monthly, POST /activity, GET /activity/summary
- GET /field/soil, /field/parcels (흙토람·팜맵 어댑터+Mock폴백)
- external_api_hub: naas_soil_by_pnu, farmmap_parcels
- crop_config 제주7종, kamis_fetcher ITEM_CODES 제주7종
