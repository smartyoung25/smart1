# 📊 KAASA SmartOS — 주간 개선 보고서 WR2
**기간: 2026-05-26 (화) ~ 2026-05-30 (토)**
**브랜치: master | 프로젝트: C:/smart_farm**

---

## 전체 통계

| 항목 | 수치 |
|------|------|
| 총 커밋 수 | **112건** |
| 변경 파일 수 | **49개** |
| 추가 코드 | **+8,491줄** |
| 삭제 코드 | **-4,183줄** |
| 순 증가 | **+4,308줄** |
| 일평균 커밋 | 22.4건/일 |

---

## 일자별 요약

| 날짜 | 커밋 | 주요 테마 |
|------|------|----------|
| 5/26 (화) | 4건 | 블랙아웃 근본 수정 · nginx 진입점 자동 감지 |
| 5/27 (수) | 4건 | Phase 46 — 와이어프레임 전체 HTML 재구성 + 라이트 테마 |
| 5/28 (목) | 28건 | Phase 47~49 — XSS 전수점검 · 다크 GitHub 테마 · 대형 버그배치 |
| 5/29 (금) | 59건 | JS 모듈 분리 완료 · 모바일 최적화 Phase 1~5 · 모델 재학습 |
| 5/30 (토) | 17건 | 모바일 미구현 보완(Phase 6) · trCls 버그 수정 · CSS 리팩토링 |

---

## 영역별 상세 내역

---

### 1. 대시보드 JS 모듈 분리 (5/29) — 핵심 아키텍처 개선

**목표**: 6,803줄짜리 단일 `index.html` → 관리 가능한 구조로 분리

| 결과물 | 내용 |
|--------|------|
| `dashboard/index.html` | 2,961줄 (전체의 43%로 축소) |
| `dashboard/style.css` | CSS 전체 분리 |
| `dashboard/modules/core.js` | 공통 유틸 (토스트, $, 포맷터) |
| `dashboard/modules/auth.js` | 로그인·토큰·농장 선택 |
| `dashboard/modules/admin.js` | 관리자 대시보드·농장 현황 |
| `dashboard/modules/environ.js` | 환경 제어·이상감지·DLI |
| `dashboard/modules/harvest.js` | 생육·수확량 예측 |
| `dashboard/modules/market.js` | 출하·가격·수익성 ERP |
| `dashboard/modules/irrigation.js` | 관수·양액·Priva ET₀ |
| `dashboard/modules/journal.js` | 생육·수확·환경·관수 이력 타임라인 |
| `dashboard/modules/chat.js` | AI 채팅 멀티프로바이더 |
| `dashboard/modules/nav.js` | 섹션 전환·사이드바 |

**커밋 이력**:
| 커밋 | 내용 |
|------|------|
| `af4c4a8` | refactor: index.html 6803줄 → 2961줄 (JS 분리) |
| `1252e36` | refactor: main.js → 9개 모듈 분리 완료 |
| `af165b6` | refactor: main.js 삭제 (모듈 분리 완료 정리) |
| `a386769` | refactor: CSS 분리 — index.html → style.css |

---

### 2. 모바일 퍼스트 최적화 — Phase 1~6 완료 (5/29~5/30)

**목표**: 360~430px 모바일에서 완전한 UX 제공 (작업지시서 `KAASA_SmartOS_모바일최적화_작업지시서.docx` 기반)

| Phase | 내용 | 커밋 |
|-------|------|------|
| Phase 1 | 전역 반응형 CSS + 하단 탭바(bottom-nav) + 햄버거 드로어 | `feat(mobile)` |
| Phase 2+3 | 섹션별 반응형 HTML/CSS + Bottom Sheet · Sticky Bar · status-badge | `feat(mobile)` |
| Phase 4 | HTML 섹션 구조 최적화 (sec-irrigation 타임라인, sec-market 스와이프카드) | `feat(mobile)` |
| Phase 5 | 전역 그리드 반응형 완성 + 테이블 오버플로우 처리 | `feat(mobile)` |
| Phase 6 | 작업지시서 미구현 9건 전체 처리 (status-ring, 라디오카드, To-do 배지 등) | `feat(mobile)` |

**브레이크포인트 전략**:
```
xs (360~430px): 1열, 사이드바→드로어, 하단 탭바 60px
sm (431~767px): 2열, 탭바 유지
md (768~1099px): 2~3열, 드로어 or 상단 탭
lg (1100px+):   데스크탑 사이드바 레이아웃 (기존 유지)
```

**터치 타겟**: 버튼 44px+, pill 36px+, bn-tab 60px

---

### 3. UI/UX 전면 개선 — Phase 46~49 (5/27~5/28)

#### Phase 46 — 와이어프레임 전체 재구성 (5/27)

```
KAASA SmartOS 전체 화면 와이어프레임 기반 HTML 재구조화
라이트 테마 → GitHub Dark 스타일 다크 테마 전면 전환
```

#### Phase 47~48 — 보안·버그 대량 수정 (5/28)

| 분류 | 항목 수 | 대표 커밋 |
|------|--------|---------|
| XSS 이스케이프 전수 적용 | ~15건 | `fix(dashboard): 전역 XSS 이스케이프 완결` |
| API 응답 구조 불일치 수정 | 3건 | `fix(dashboard): API 응답 구조 불일치 3건` |
| 백엔드·프런트 데이터 불일치 | 핵심 | `@ fix: Phase 48 — 백엔드·프런트엔드 데이터 불일치` |
| admin.py ZeroDivisionError | 1건 | `fix(api): ZeroDivisionError 방지` |
| farmer.py 논리 버그 | 3건 | `fix(api): farmer.py 논리 버그 3건` |
| SQL 화이트리스트 검증 누락 | 1건 | `fix(api): data_collection.py 화이트리스트 검증` |
| 날씨예보 날짜 XSS | 1건 | `fix(dashboard): 날씨예보 날짜XSS·병해숫자강제변환` |

#### Phase 49 — 추가 개선 (5/28)

| 커밋 | 수정 내용 |
|------|---------|
| `fix(api+dashboard): 다중 버그 수정 및 UI 개선 Phase 49` | whatif yield 역산, crop_ko 별칭, populateSelectWithFarms 선택값 보존 |
| `fix(dashboard): loadProfitForecast NaN 방지` | 수익 예측 수치 NaN 방지 |
| `fix(dashboard,api): apply 권고 422 수정` | priva 500 예외 로깅 추가 |
| `fix(dashboard): 채팅 이력 추가` | XSS방지, 중복함수제거, 대화초기화버튼 |

---

### 4. AI 모델 개선 (5/29)

| 작물 | 이전 MAPE | 개선 후 MAPE | 변경 내용 |
|------|---------|------------|---------|
| 참외 | 396.3% | 63.9% | `min_train_samples` 30→60, Ridge 잔차 모드 강제 |
| 오이 | - | 22.8% | 레거시 pkl → 신규 재학습 (CV R²=0.826) |
| 딸기·방울토마토·완숙토마토 | - | (각 MAPE floor 수정 후 재학습) | near-zero MAPE 인플레이션 수정 |

**M2 게이트 표시 수정**:
- `/models` 엔드포인트 → `stage2_meta.json` 권위적 소스 사용
- `cv_mape_mean` 우선순위 역전 수정
- MAPE > 100% 시 gate_pass 강제 False

**커밋**:
| 커밋 | 내용 |
|------|------|
| `6798eac` | fix(m2): 참외 MAPE 396%→64% |
| `70669b8` | chore(model): 참외·오이 M2 재학습 메타 업데이트 |
| `fix(m2)` | near-zero MAPE 인플레이션 수정 + 오이/참외 재학습 |

---

### 5. 저널 이력 시스템 신설 (5/29~5/30)

새로운 `journal.js` 모듈: 생육·수확·환경·관수 이력을 시각적 타임라인으로 표시

| API | 내용 |
|-----|------|
| `GET /api/farms/{id}/growth-records` | 생육 측정 이력 |
| `GET /api/farms/{id}/harvests` | 수확량 이력 |
| `GET /api/farms/{id}/environment` | 환경 측정 이력 |
| `GET /api/farms/{id}/irrigation` | 관수 이력 |

**렌더 함수 4개**: `_renderHarvestTimeline`, `_renderEnvTimeline`, `_renderIrrigationTimeline`, `_renderGrowthTimeline`

---

### 6. 야간 파이프라인 및 백엔드 안정화 (5/29)

| 항목 | 내용 | 커밋 |
|------|------|------|
| ETL 야간 스케줄 경로 수정 | 3종 스케줄 태스크 버그 수정 | `fix(pipeline)` |
| PGPASSWORD 수정 | 구 패스워드 → 현재 패스워드 | `fix(backup)` |
| ETL 로그 스크롤 버그 | `.log-box/.log-line` CSS 추가 | `1e48ccf` |
| nightly_db_etl 버그 3건 | `fix(etl)` | |
| 보안패치 — 입력검증·인젝션 방지 | `security(admin)` | |
| API 폴링 최적화 | 백엔드 KeyError 방지 + 프론트 폴링 최적화 | |

---

### 7. 레이아웃 치명적 버그 수정 (5/26·5/30)

| 커밋 | 버그 | 수정 |
|------|------|------|
| `1e0fb0c` (5/26) | sec-dashboard `</div>` 누락 → 전 메뉴 블랙아웃 | 닫힘 태그 복원 |
| `fix(ui)` (5/26) | position:absolute 방식 이탈 | 복원 |
| `fix(nginx)` (5/26) | 로그인 폼 API URL 하드코딩 | `location.origin` 자동 감지 |
| `0fb57c3` (5/30) | `.sec { left: 192px }` 오버인덴트 | `left: 0` 복원 |
| `ebe29e3` (5/30) | journal.js `trCls` undefined → `<trundefined>` 렌더 (4건) | `const trCls` 올바른 선언 |
| `b182934` (5/30) | environ 이상감지 카드 비어있는 버그 3건 | API 응답 키 매핑 수정 |

---

## 회귀 테스트 결과 (5/30 전수 점검)

| 모듈 | 점검 항목 | 결과 |
|------|---------|------|
| core.js | `$()`, `setText()`, `showToast()` 동작 | ✅ |
| auth.js | 로그인·로그아웃·JWT 갱신 | ✅ |
| admin.js | 30초 폴링 `document.hidden` 가드 | ✅ |
| environ.js | DLI 계절 보정 (5월 13h → 15.0 mol/m²d) | ✅ |
| harvest.js | `advices||[]` 방어코드 | ✅ |
| market.js | null 가격 `—` 표시, NaN 방지 | ✅ |
| irrigation.js | Priva ET₀ 카드, 이력 타임라인 | ✅ |
| journal.js | trCls 4건 수정 → 정상 줄무늬 렌더 | ✅ |
| chat.js | 멀티프로바이더 응답, XSS 방지 | ✅ |
| nav.js | 옵셔널 체이닝 `?.classList` | ✅ |
| layout | 전 섹션 `left=0px`, 섹션 전환 정상 | ✅ |
| **전체** | **10개 모듈 회귀 PASS** | **✅** |

---

## 잔여 작업 / 다음 단계

| 우선순위 | 항목 | 상태 |
|---------|------|------|
| 🔴 긴급 | 토마토 계열 M1 ERA5 실측 CSV 확보 후 재학습 (R² 음수) | 미완 |
| 🟡 중간 | M2 포맷 통합 A/B/C → 단일 `YieldPredictor` | 미완 |
| 🟡 중간 | drift 모니터링 — 실측 vs 예측 자동 비교 | 미완 |
| 🔵 인프라 | GitHub push (origin/master 107 커밋 뒤처짐) | 보류 |
| 🔵 인프라 | WSL2 → Docker → DuckDNS → Let's Encrypt (사용자 액션) | 보류 |

---

## 시스템 현황 (2026-05-30 기준)

| 항목 | 상태 |
|------|------|
| FastAPI (포트 8000) | ✅ 운영 중 |
| PostgreSQL 17 + TimescaleDB | ✅ 운영 중 |
| MQTT (mosquitto) | ✅ 운영 중 |
| 대시보드 (index.html) | ✅ 2,961줄 (모듈 분리 완료) |
| M2 게이트 PASS 작물 | 딸기·방울토마토·완숙토마토·파프리카·오이·참외 (전 6종) |
| 모바일 최적화 | ✅ Phase 1~6 완료 (360~430px 대응) |
| XSS 이스케이프 | ✅ innerHTML 전수 적용 완료 |

---

*생성일: 2026-05-30 | 담당: KAASA SmartOS Dev*
