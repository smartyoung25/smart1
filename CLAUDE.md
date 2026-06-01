# KAASA SmartOS — 작업 메모리 (CLAUDE.md)
> 매 세션 시작 시 이 파일을 반드시 먼저 읽을 것.
> 매 세션 종료 시 결정사항·진행상태·남은 일을 반드시 이 파일에 기록할 것.

---

## ★ 핵심 재정의 (2026-05-31 확정)

### P1~P5는 하루 관수 Period (Priority가 아님)
| Period | 시간대 | 의미 | 핵심 지표 |
|--------|--------|------|-----------|
| P1 | 일출 전 (05:00~07:00) | 관수 준비·첫 관수 前 점검 | EC/pH 기준값, 야간 배액 잔량 |
| P2 | 오전 첫 관수 (07:00~10:00) | 첫 급액 — 근권 활성화 | 급액 EC, 배액률 목표 20~30% |
| P3 | 오전 중반 (10:00~12:00) | 일사 상승 대응 추가 관수 | DLI 누적, VPD 상승 |
| P4 | 정오 고부하 (12:00~15:00) | 최대 증산·고부하 급액 | 배액률 12%↑ 이면 즉시 추가 |
| P5 | 오후~마감 (15:00~일몰) | 야간 준비, 마지막 급액 | EC 상향 조정, 배액 완료 확인 |

**작업지시서의 P1/P2/P3 우선순위 표기는 전면 폐기. Period 기반 화면 설계로 전환.**

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

---

## 완료된 화면 (2026-06-01 기준)

| 화면 | 파일 | 주요 기능 |
|------|------|-----------|
| C3 통합 홈 | screens/c3_home.html | To-do·KPI·AI 72%·가격 스트립 |
| G3 관수·양액 | screens/g3_period.html | P1~P5·Priva ET₀·DB 실저장 |
| G2 환경 제어 | screens/g2_env.html | KPI 6종·모드 4단계·규칙 추천 |
| G4 생육 모델 | screens/g4_growth.html | D-31·생육단계·M1/M2 성능 |
| G5 병해·품질 | screens/g5_disease.html | M5 위험도·이상값·방제조언 |
| G6 수확·유통 | screens/g6_harvest.html | 채널 비교·시나리오·수익성 |
| C5 수익성 ERP | screens/c5_erp.html | 원가·마진율 89%·BEP·절감 |
| 네비게이터 | index.html → /smartos | 7개 완료 표시 |

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
