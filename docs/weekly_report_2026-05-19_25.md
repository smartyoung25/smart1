# 📊 스마트팜 AI 플랫폼 — 주간 작업내역 보고서
**기간: 2026-05-19 (월) ~ 2026-05-25 (일)**
**브랜치: master | 프로젝트: C:/smart_farm**

---

## 전체 통계

| 항목 | 수치 |
|------|------|
| 총 커밋 수 | **37건** |
| 변경 파일 수 | **312개** |
| 추가 코드 | **+38,280줄** |
| 삭제 코드 | **-1,432줄** |
| 일평균 커밋 | 5.3건/일 |

---

## 일자별 요약

| 날짜 | 커밋 | 주요 작업 |
|------|------|----------|
| 5/19 (월) | 2건 | 배포 인프라 기반 — PostgreSQL 연결·CSV 파싱 수정 |
| 5/20 (화) | 9건 | nginx/HTTPS/DNS 배포 완성 + M2 전작목 재학습 |
| 5/21 (수) | 3건 | 논문 기반 생리 피처 + M2 전작목 게이트 PASS |
| 5/22 (목) | 5건 | UI/UX 전면 개선 + 사용자 계정 시스템 |
| 5/23 (금) | 10건 | M5 병해탐지·외부 API·커버리지 85.55%·AquaCrop |
| 5/24 (토) | 1건 | Phase 43 데이터 수집 자동화 정리 커밋 |
| 5/25 (일) | 7건 | SFROP v2.0 + 블랙아웃 버그 근본 수정 |

---

## 영역별 상세 내역

---

### 1. 배포 인프라 (5/19~5/20) — Phase 35

```
nginx 리버스 프록시 설정 (80/443 포트)
HTTPS 자체 서명 인증서 생성 + DuckDNS 동적 DNS 연동
Windows 서비스 자동 시작 스크립트
pyproject.toml / requirements.txt 정비
```

| 커밋 | 내용 |
|------|------|
| `f400a73` | feat(deploy): nginx 리버스 프록시·Windows 자동화 설정 추가 |
| `9cf7d64` | feat(deploy): HTTPS 자체 서명 인증서 + DuckDNS 동적 DNS 설정 |
| `899ca5b` | feat(ops): 운영 안정화 — 대시보드 로그인 수정 + 배포 인프라 완성 |
| `3fe15f0` | chore(deps): pyproject.toml 및 requirements 파일 추가 |
| `fb2fe49` | fix(pipeline): initial_load PostgreSQL 연결 및 CSV 인코딩/컬럼 수정 |

---

### 2. AI 모델 개선 (5/20~5/23) — Phase 38~42

#### M2 수확량 모델 전작목 재학습 (5/20~5/21)

```
임계이벤트 피처 적용 (VPD 과열·저온·일사량 부족 카운트)
작기단계 인식 피처 (days_since_plant, growth_stage_label)
VPD 최적 범위 내 비율 피처
전 작목 게이트 PASS (MAPE < 기준치)
```

| 커밋 | 내용 |
|------|------|
| `5af7b86` | feat(model): M2 수확량 모델 전작목 재학습 — 임계이벤트 피처 적용 |
| `e0bdad7` | feat(accuracy): 환경 최적화 + 소득최적화 정확도 개선 (VPD·작기단계·임계이벤트) |
| `68bc80d` | M2 수확량 모델 정확도 개선 — 전 작목 게이트 PASS |

#### 논문 기반 생리학적 피처 추가 (5/21)

```
VPD × EC 상호작용항 (광합성 효율 기반)
야간 기온 패널티 (딸기·참외 특이 피처)
누적 일사량 × 생육단계 교차항
```

| 커밋 | 내용 |
|------|------|
| `efe176e` | 논문 기반 생리학적 피처 추가 — 전작목 정확도 개선 |

#### 글로벌 우수모델 + NASA POWER API 통합 (5/23)

```
EWM(지수가중평균, span=3) 환경 피처 — 최근 트렌드 강조
누적 GDD (gdd_cumsum, gdd_lag1, gdd_lag2) — AquaCrop/DSSAT 기반
DLI (Daily Light Integral) 추정 피처
NASA POWER API → 실제 기상 피처 보완
World Bank API → 지역 농업 통계 연동
yield lag 피처 (이전 작기 수확량 참조)
```

| 커밋 | 내용 |
|------|------|
| `115af1b` | feat: 글로벌 우수모델 기반 M1/M2 성능 향상 + NASA POWER/World Bank API 통합 |
| `c3cb741` | feat: 전 작목 M1/M2 재학습 — yield lag 피처 적용 결과 |
| `6b48767` | feat: Phase 41 — RMSE/MAE 지표 추가, M1/M2 성능 향상, 디지털트윈 매핑 문서화 |

#### AquaCrop 물리피처 통합 (5/23)

```
FAO AquaCrop 기반 토양수분균형 계산
신뢰도 등급 UI 카드 추가 (A/B/C/D 등급)
```

| 커밋 | 내용 |
|------|------|
| `f0c8475` | Phase 42: AquaCrop 물리피처 통합 + 신뢰도 등급 UI |

#### M1/M2 성능 현황 (5/23 기준)

| 작목 | M1 R² (Phase 44) | M2 MAPE |
|------|-----------------|---------|
| 딸기 | 0.381 | 22.4% |
| 완숙토마토 | 0.294 | 18.7% |
| 방울토마토 | 0.218 | 28.3% |
| 파프리카 | 0.142 | 24.1% |
| 참외 | 0.089 | 31.2% |
| 오이 | 0.063 | — |

---

### 3. 데이터 파이프라인 (5/20~5/23) — Phase 43

#### 어댑터 수정 (5/20)

```
이암허브 다중 인코딩 처리 (UTF-8 / CP949 / EUC-KR 자동 감지)
컬럼명 정규화 / 타임스탬프 파싱 수정
ZIP 라우팅 및 생육데이터 분기 처리
관수 어댑터 (irrigation_adapter.py) 신규 추가
```

| 커밋 | 내용 |
|------|------|
| `3619576` | fix(adapters): 이암허브 다중 인코딩·컬럼명·타임스탬프 파싱 수정 |
| `e8119ab` | fix(pipeline): ZIP 라우팅 및 생육데이터 분기 처리 |
| `5ae8464` | feat(adapters): irrigation adapter 추가 및 base_adapter·farmer 라우터 개선 |

#### 오이 작목 파이프라인 추가 (5/23)

```
오이 crop_config.py 등록
M1 학습·추론 파이프라인 전체 통합
```

| 커밋 | 내용 |
|------|------|
| `4014ad3` | feat: 오이(cucumber) 전체 파이프라인 추가 + crop_config.py 등록 |

#### 데이터 수집 자동화 (5/23~5/24)

```
growth / harvest JSON 자동 수집·저장
딸기 10건, 방울토마토 2건 (growth)
딸기 13건, 오이 2건, 파프리카 2건 (harvest)
```

| 커밋 | 내용 |
|------|------|
| `4ad41f2` | Phase 43: 데이터 수집 자동화 파이프라인 |
| `27ec683` | Phase 43 누적 변경사항 정리 커밋 |

---

### 4. 외부 API 연동 (5/22~5/23) — Phase 38

#### M5 병해탐지 4계층 API (5/23)

```
1계층: Plant.id API (딥러닝 식물병 인식)
2계층: NCPMS (농촌진흥청 병해충 발생 예보)
3계층: M5 규칙기반 (VPD·온습도 임계치)
4계층: EPPO 폴백 (유럽 병해충 데이터베이스)
```

#### 도매가격 다중 소스 연동

```
aT 농산물유통정보 API
KAMIS 실시간 시세 캐시
FAO FAOSTAT 국제 가격 통계
M2 RDA 기준값 클리핑 (방울토마토 231% 과적합 수정)
```

| 커밋 | 내용 |
|------|------|
| `1fd8ba8` | feat: M5 병해탐지 4계층 API + M2 RDA 클리핑 + aT/KAMIS/FAO 도매가격 연동 |

---

### 5. 테스트 커버리지 (5/23) — Phase 37

```
irrigation_store 모듈 테스트 추가
persistence 레이어 테스트 추가
at_wholesale_service 테스트 추가
anomaly_detector 테스트 추가

85.35% → 85.55% 달성 (1,147 PASS)
```

| 커밋 | 내용 |
|------|------|
| `2f984fa` | test: 커버리지 85.35% — irrigation_store·persistence·at_wholesale·anomaly 추가 |
| `f2b73c2` | test: Phase 37 어댑터 커버리지 85.55% 달성 |

---

### 6. UI/UX 개선 (5/21~5/22)

#### 대시보드 전면 개선 (5/22)

```
접근성: ARIA 레이블, 키보드 네비게이션
폼 구조화: 필드 그룹핑, 유효성 검사 UI
피드백: 로딩 스피너, 토스트 알림, 오류 메시지
```

#### 버그 수정

```
생산·유통 탭 가격 표시 오류 수정
가격이력 작목 파라미터 수정
현장 점검 순서 메뉴 재편
서버 재시작 스크립트 추가
대시보드 섹션 공백 버그 수정
```

| 커밋 | 내용 |
|------|------|
| `db9d6c4` | feat(dashboard): UI/UX 전면 개선 — 접근성·피드백·폼 구조화 |
| `7d70821` | fix: 생산·유통 가격 표시 오류·가격이력 작목 파라미터·서버 재시작 스크립트 |
| `563fdbf` | Phase 35-4: 대시보드 섹션 공백 버그 수정·현장 점검 순서 메뉴 재편 |

---

### 7. 사용자 계정 시스템 (5/22)

```
회원가입 / 로그인 / JWT 토큰 발급
온보딩 5단계 프로필 저장 (farm_id, crop, area, region)
PostgreSQL users 테이블 연결 수정
farm_registry.json 신규 농장 자동 등록 (온보딩 시 82개)
```

| 커밋 | 내용 |
|------|------|
| `37f2278` | feat: 사용자 계정 시스템 + PostgreSQL DB 연결 수정 |

---

### 8. SFROP v2.0 — Phase 45 (5/25)

#### ERP 실시간 수익성 엔진

**신규 파일: `api/engine/erp_calculator.py`**

```
에너지비 / 양액비 / 노동비 / 종묘비 자동 집계 (RDA 2022 기준)
KAMIS 도매가 연동 → kg당 마진·소득률·손익분기 산출
출하 타이밍 조언 (오늘 vs 내일 마진 비교)
작기단계별 LED 스펙트럼 권장 (발아/영양생장/착화/성숙)
```

**신규 엔드포인트:** `GET /api/farms/{farm_id}/erp/realtime`

**대시보드 추가 UI:**
- 실시간 수익성 카드 (원가·마진·소득률·손익분기)
- LED 스펙트럼 권장 카드 (R:B:UV 비율 + 효과)
- 4개 시나리오 비교 패널 (현재기준 / 생육최적화 / 에너지최적화 / AI통합최적화)

#### ERA5 기상 피처 통합

**신규 파일: `adapters/era5_features.py`**

```
ERA5-Land CSV → GDD정규화 / CU_norm / ET0_mm / DIF / NDVI_proxy / 누적일사량
폴백 체계: ERA5 CSV → NASA POWER API → KMA 내부온도 합성
5개 지역 CDS API 일괄 다운로드 CLI (data/weather/era5/ 저장)
era5_download_run.py (smartfarm-mvp) 로직 포팅
```

**5개 지역 좌표:**

| 지역 | 위도 | 경도 | 주요 작목 |
|------|------|------|---------|
| 경북 성주 | 35.92°N | 128.28°E | 참외 |
| 충남 논산 | 36.19°N | 127.10°E | 딸기 |
| 전북 익산 | 35.94°N | 126.95°E | 딸기 |
| 경기 평택 | 36.99°N | 127.11°E | 토마토 |
| 경남 합천 | 35.57°N | 128.17°E | 오이 |

**M1 학습 파이프라인:** `train_stage1_growth.py` Step 7 — ERA5 피처 +12컬럼 자동 주입

| 커밋 | 내용 |
|------|------|
| `c4e5227` | feat(Phase 45): SFROP v2.0 대시보드 통합 — ERP 실시간 수익성 + LED 스펙트럼 + 4개 시나리오 |
| `0176695` | feat(Phase 45): ERA5 기상 피처 통합 + M1 전작목 재학습 |

---

### 9. 대시보드 블랙아웃 근본 수정 (5/25) — Phase 44~45

#### 원인 분석

```css
/* 문제: #content-area 높이 미계산 시 모든 섹션 0px 렌더링 */
#content-area { position: relative; overflow: hidden; }
.sec { position: absolute; top: 0; left: 0; right: 0; bottom: 0; }
```

#### 수정 내용

```css
/* 수정: flex:1 방식으로 전환 — 브라우저 호환성 향상 */
#content-area {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sec {
  flex: 1;
  width: 100%;
  min-height: 0;
}
```

**추가 수정:**
- 신규 가입 농가 빈 화면 → 작목별 시뮬레이션 데이터 자동 주입
- 환경탭 신규 농가 빈 화면 버그 수정

| 커밋 | 내용 |
|------|------|
| `b01723a` | fix: 대시보드 메뉴 섹션 블랙아웃 버그 수정 (Phase 44) |
| `a7c4ec8` | fix(dashboard): 모든 섹션 블랙아웃 근본 수정 — position:absolute → flex:1 레이아웃 |
| `7cefcde` | fix(environ): 신규 가입 농가 환경탭 빈 화면 버그 수정 |
| `4876355` | feat(dashboard): 신규 농가 빈 화면 — 작목별 시뮬레이션 데이터 주입 |

---

### 10. 데이터 정리 및 gitignore 개선 (5/25)

```
kamis_price_cache.json: git 추적 제거 (런타임 캐시)
/env: API 키 포함 파일 제외 추가
cols_check.txt, pdf_extract*.txt: 디버그 임시 파일 제외
farm_registry.json: 온보딩 82개 농장 자동 등록 반영
```

| 커밋 | 내용 |
|------|------|
| `ee438d6` | chore(data): 수집 데이터 정리 및 gitignore 개선 |

---

### 11. 문서화

| 커밋 | 내용 |
|------|------|
| `6fecacc` | docs: 아키텍처 문서 Phase 39 업데이트 |
| `21cc39c` | docs: 스마트팜 엔진 설계표 문서 추가 |
| `10775f4` | docs: 2026-05-22 UI/UX 개선 작업내역 추가 |

---

## 완료된 주요 마일스톤

| 마일스톤 | 완료일 | 상태 |
|---------|--------|------|
| Phase 35 — 배포 인프라 완성 (nginx/HTTPS/DuckDNS) | 5/20 | ✅ |
| Phase 36 — 어댑터 파이프라인 수정 | 5/20 | ✅ |
| Phase 37 — 테스트 커버리지 85.55% | 5/23 | ✅ |
| Phase 38 — M5 병해탐지 4계층 API | 5/23 | ✅ |
| Phase 39 — 아키텍처 문서화 | 5/23 | ✅ |
| Phase 40 — NASA/World Bank API 통합 | 5/23 | ✅ |
| Phase 41 — RMSE/MAE 지표·디지털트윈 | 5/23 | ✅ |
| Phase 42 — AquaCrop 물리피처 | 5/23 | ✅ |
| Phase 43 — 데이터 수집 자동화 파이프라인 | 5/24 | ✅ |
| Phase 44 — 대시보드 블랙아웃 수정 | 5/25 | ✅ |
| Phase 45 — SFROP v2.0 ERP+ERA5 통합 | 5/25 | ✅ |

---

## 전체 커밋 목록 (시간순)

| 날짜 | 커밋 | 내용 |
|------|------|------|
| 5/19 | `fb2fe49` | fix(pipeline): initial_load PostgreSQL 연결 및 CSV 인코딩/컬럼 수정 |
| 5/19 | `109047c` | feat(phase31-35): UI수정·엔진검증·테스트·배포준비 완료 |
| 5/20 | `3fe15f0` | chore(deps): pyproject.toml 및 requirements 파일 추가 |
| 5/20 | `f400a73` | feat(deploy): nginx 리버스 프록시·Windows 자동화 설정 추가 |
| 5/20 | `9cf7d64` | feat(deploy): HTTPS 자체 서명 인증서 + DuckDNS 동적 DNS 설정 |
| 5/20 | `899ca5b` | feat(ops): 운영 안정화 — 대시보드 로그인 수정 + 배포 인프라 완성 |
| 5/20 | `e0bdad7` | feat(accuracy): 환경 최적화 + 소득최적화 정확도 개선 |
| 5/20 | `5af7b86` | feat(model): M2 수확량 모델 전작목 재학습 — 임계이벤트 피처 적용 |
| 5/20 | `5ae8464` | feat(adapters): irrigation adapter 추가 및 base_adapter·farmer 라우터 개선 |
| 5/20 | `3619576` | fix(adapters): 이암허브 다중 인코딩·컬럼명·타임스탬프 파싱 수정 |
| 5/20 | `e8119ab` | fix(pipeline): ZIP 라우팅 및 생육데이터 분기 처리 |
| 5/21 | `68bc80d` | M2 수확량 모델 정확도 개선 — 전 작목 게이트 PASS |
| 5/21 | `efe176e` | 논문 기반 생리학적 피처 추가 — 전작목 정확도 개선 |
| 5/21 | `563fdbf` | Phase 35-4: 대시보드 섹션 공백 버그 수정·현장 점검 순서 메뉴 재편 |
| 5/22 | `7d70821` | fix: 생산·유통 가격 표시 오류·가격이력 작목 파라미터·서버 재시작 스크립트 |
| 5/22 | `db9d6c4` | feat(dashboard): UI/UX 전면 개선 — 접근성·피드백·폼 구조화 |
| 5/22 | `10775f4` | docs: 2026-05-22 UI/UX 개선 작업내역 추가 |
| 5/22 | `21cc39c` | docs: 스마트팜 엔진 설계표 문서 추가 |
| 5/22 | `37f2278` | feat: 사용자 계정 시스템 + PostgreSQL DB 연결 수정 |
| 5/23 | `1fd8ba8` | feat: M5 병해탐지 4계층 API + M2 RDA 클리핑 + aT/KAMIS/FAO 도매가격 연동 |
| 5/23 | `f2b73c2` | test: Phase 37 어댑터 커버리지 85.55% 달성 |
| 5/23 | `2f984fa` | test: 커버리지 85.35% — irrigation_store·persistence·at_wholesale·anomaly 추가 |
| 5/23 | `4014ad3` | feat: 오이(cucumber) 전체 파이프라인 추가 + crop_config.py 등록 |
| 5/23 | `6fecacc` | docs: 아키텍처 문서 Phase 39 업데이트 |
| 5/23 | `115af1b` | feat: 글로벌 우수모델 기반 M1/M2 성능 향상 + NASA POWER/World Bank API 통합 |
| 5/23 | `c3cb741` | feat: 전 작목 M1/M2 재학습 — yield lag 피처 적용 결과 |
| 5/23 | `6b48767` | feat: Phase 41 — RMSE/MAE 지표 추가, M1/M2 성능 향상, 디지털트윈 매핑 문서화 |
| 5/23 | `f0c8475` | Phase 42: AquaCrop 물리피처 통합 + 신뢰도 등급 UI |
| 5/23 | `4ad41f2` | Phase 43: 데이터 수집 자동화 파이프라인 |
| 5/24 | `27ec683` | Phase 43 누적 변경사항 정리 커밋 |
| 5/25 | `b01723a` | fix: 대시보드 메뉴 섹션 블랙아웃 버그 수정 (Phase 44) |
| 5/25 | `c4e5227` | feat(Phase 45): SFROP v2.0 대시보드 통합 — ERP 실시간 수익성 + LED 스펙트럼 + 4개 시나리오 |
| 5/25 | `0176695` | feat(Phase 45): ERA5 기상 피처 통합 + M1 전작목 재학습 |
| 5/25 | `7cefcde` | fix(environ): 신규 가입 농가 환경탭 빈 화면 버그 수정 |
| 5/25 | `4876355` | feat(dashboard): 신규 농가 빈 화면 — 작목별 시뮬레이션 데이터 주입 |
| 5/25 | `a7c4ec8` | fix(dashboard): 모든 섹션 블랙아웃 근본 수정 — position:absolute → flex:1 레이아웃 |
| 5/25 | `ee438d6` | chore(data): 수집 데이터 정리 및 gitignore 개선 |

---

*생성일: 2026-05-25 | 작성: Claude Sonnet*
