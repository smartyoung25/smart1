# 글로벌 스마트농업 의사결정 시스템 UI 벤치마킹 → KAASA SmartOS 적용

> 작성 2026-06-01 · 대상: 모바일 퍼스트 온실+노지 통합 관리 UI

## 1. 벤치마킹 대상 (실제 글로벌 제품)

| 제품 | 영역 | 핵심 UI 시사점 |
|------|------|----------------|
| **Priva Connext / Operator** | 온실 환경제어 | "조치가 필요한 것"을 먼저 띄우는 attention-routing 홈 · 작물/구획/역할별 컨텍스트 대시보드 · 원클릭 드릴다운 + 변경 이력 복원 |
| **Hoogendoorn iSii + LetsGrow** | 데이터 기반 재배 | 모든 소스(기후·센서·ERP·등급·노동·에너지)를 한 화면에 · 수확량 4주 예측을 "계획 산출물"로 제시 · 타 농가 벤치마킹 |
| **30MHz / Aranet** | 센서 대시보드 | 사용자 조립형 위젯 · 값을 지도/사진 위 히트맵으로 · 데이터 알림 vs 기기(배터리·연결) 알림 분리 |
| **Source.ag** | AI 의사결정 | 자연어 어시스턴트(작물·생육단계 스코프) · "대체가 아닌 증강" human-in-the-loop · 예측을 사업행동(계약)에 연결 |
| **iFarm Growtune** | 수직농장 | Gantt 식재 계획 · "레시피 이탈(off-recipe)" 기준 편차 조기경보 · 긴급경보 계층 분리 |
| **John Deere Ops Center** | 노지·장비 | 카드 기반 task-routing 홈 · 알림+이력 한곳 통합 · 계획→전송→사진/메모로 완료기록 폐루프 |
| **Climate FieldView** | 노지 | 토양/파종/시비/수확/위성/기상 peelable 레이어 지도 · 실시간 패스 시각화 · 지도 나란히 비교 |
| **CropX / Sentek** | 토양·관개 | 이상감지 + 처방을 한 항목에("저수분 → X 관수") · 깊이·생육단계 스케줄 |
| **Autogrow / Bluelab** | 양액 도징 | 주/야 EC·pH setpoint 시간분할 · 선택 기능만 노출(progressive disclosure) · 과투입 잠금장치 |

## 2. Top 12 벤치마크 패턴 → 우리 적용 상태

| # | 패턴 | 대표 제품 | KAASA 적용 |
|---|------|-----------|-------------|
| 1 | Attention-routing 홈 | Priva·JohnDeere | ✅ C3·G1·F1 "오늘의 결정" 섹션 |
| 2 | 컨텍스트 스코프 대시보드 | Priva | ✅ P1~P5 Period 보드 + 작물별 맞춤메뉴 |
| 3 | **이상감지+처방 한 카드 + 원탭 실행** | CropX | ✅ **DecisionDeck (C3·G1·F1)** |
| 4 | Human-in-the-loop AI(신뢰도·승인) | Source.ag | ✅ 결정카드 신뢰도% + 적용/근거 버튼 |
| 5 | 예측-with-horizon | LetsGrow | ✅ M2 수확 30일 예측(g4) |
| 6 | 기준대비 편차(setpoint band) | iFarm·FieldView | ✅ **BandChart — g3 배액률 목표대 음영(신규)** |
| 7 | 값의 공간/사진 오버레이 | 30MHz·FieldView | ✅ **F2 토양수분·NDVI 히트맵(신규)** |
| 8 | 레이어 토글 지도 | FieldView | ✅ **F2 peelable 레이어 토글(신규)** |
| 9 | 계획→실행→기록 폐루프 | JohnDeere | ✅ 결정 적용→/activity 적재→retrain→리포트 |
| 10 | 시간분할 setpoint(주/야) | Bluelab | ✅ Period별 EC/pH 기준 |
| 11 | 자동화 액션 가드레일 | Bluelab | ✅ 권고 적용 등급 게이팅(tier_guard) |
| 12 | 데이터 알림 vs 기기 알림 분리 | 30MHz | ✅ **DeviceAlert — c3·g2 연결/기기 알림 분리(신규)** |

> **2026-06-01 2차 적용 완료**: 12개 패턴 전부 ✅ (◑ 4건 → 신규 컴포넌트 3종으로 해소)
> 신규: `band_chart.js`(패턴6) · `device_alert.js`(패턴12) · F2 레이어/히트맵(패턴7·8) · DecisionDeck g1/f1 확장(패턴1·3)

## 3. 우리가 차별화한 지점 (대부분의 agtech UI가 약한 곳)

1. **모바일·장갑 손 ergonomics** — 대부분 태블릿/데스크탑 파생. 우리는 하단 5탭 · 48px+ · 한손 조작 기준.
2. **신뢰도·출처·신선도 동시 노출** — 경쟁 제품은 AI 수치만 보여주고 모델 신뢰도/데이터 출처/갱신시각을 거의 안 보여줌. 우리 결정카드는 **신뢰도 바 + 출처 배지(실측/모델/표준) + "n분 전"** 3종을 한 카드에.
3. **권고 수용 추적(폐루프)** — 추천 수용 여부를 /activity로 적재해 학습에 환원(retrain_trigger). 경쟁 제품엔 없음.
4. **색상+아이콘+텍스트 3중 심각도 코딩** — 색맹/직사광 대응. (긴급🚨/주의⚠️/권장💡/정상✅ + 색 + 라벨)
5. **무설정 기본 대시보드** — 30MHz/Priva는 사용자가 직접 위젯을 조립해야 함. 우리는 작물·시설 선택만으로 맞춤 구성 자동 제공.

## 4. 이번에 최종 UI에 반영한 산출물

- `components/decision_card.css` · `components/decision_card.js` — **DecisionDeck** 재사용 컴포넌트
  - 패턴 1·3·4·9·12 + 차별화 2·4 구현
  - `DecisionDeck.render(el, items, {onApply})`
- `screens/c3_home.html` — 홈 최상단 "오늘의 결정(AI 의사결정)" 섹션
  - 배액률/VPD 이상감지 + AI 추천을 결정카드로 통합
  - 각 카드: 심각도(3중코딩)·처방액션·신뢰도·출처·신선도 + 원탭 "적용 기록"(→/activity 폐루프) + "근거"
  - 검수(Playwright): 렌더/근거토글/activity POST 정상, 콘솔 에러 0건

## 5. 2차 적용 산출물 (Top12 전부 완료)

| 신규 컴포넌트/적용 | 패턴 | 화면 |
|---|---|---|
| `components/decision_card.js` 빌더 확장 | 1·3·4·9 | g1·f1 "오늘의 결정" |
| `components/band_chart.js` (의존성0 SVG) | 6 | g3 배액률 목표대 밴드 |
| `components/device_alert.js` | 12 | c3·g2 기기/연결 알림 분리 |
| F2 peelable 레이어 + 값 히트맵 | 7·8 | f2_gis(필지경계·토양수분·NDVI) |

## 6. 향후 실데이터 주입 시 자동 고도화 (구조 완비)

- 흙토람/위성 NDVI 키 주입 → F2 히트맵이 예시값→실측으로 자동 전환(출처 배지 🟢)
- 센서 게이트웨이 배터리 텔레메트리 주입 → DeviceAlert.setDevices()로 배터리/오프라인 자동 표출
- 7일+ 관수 이력 축적 → BandChart 시계열이 점→추세선으로 자동 충실화
