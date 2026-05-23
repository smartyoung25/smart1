# 생산예측모델 전체 분석 최종 보고서

**분석 완료**: 2026-05-23  
**대상**: 딸기·방울토마토·완숙토마토·참외·파프리카 (M1/M2)  

---

## 1. 예측 vs 실측 10배 차이 — 확정된 원인

### 원인 1 (직접 원인 ★★★): 연간 예측값 vs 월별 실측 비교 혼동

| 항목 | 값 | 비고 |
|------|------|------|
| `predict_yield("딸기")` 반환 `yield_kg_m2` | **12.0 kg/m²** | **연간(시즌)** 값 |
| 사용자 월별 실측 | **1.0~2.0 kg/m²/월** | 6개월 합산 = 6~12 kg/m² |
| 직접 비교 시 오차 | **6~12배** | 단위 통일 없이 비교했을 때 |

**메커니즘**: `m2_yield.py`의 `predict_yield()`는 시즌 전체 연간 수확량(kg/m²/season)을 반환한다. 반면 `model_loader.py`의 4-stage 경로는 `revenue_annual / season_months`로 나눠 월별 값을 반환한다. 두 코드 경로가 **다른 단위**를 반환하여 혼용 비교 시 6~12배 차이가 발생한다.

### 원인 2 (구조 원인 ★★★): 학습 데이터 수확량 과대 — 면적 오기록 아웃라이어

| 작물 | farm_encoding.global_mean | RDA 정상 상한 | 배율 |
|------|--------------------------|--------------|------|
| 완숙토마토 | **75.14** kg/m²/년 | 30.0 | **2.5배 초과** |
| 파프리카 | **55.54** kg/m²/년 | 20.0 | **2.8배 초과** |
| 참외 | 16.86 kg/m²/년 | 12.0 | 1.4배 초과 |
| 딸기 | 16.77 kg/m²/년 | 12.0 | 1.4배 초과 |
| 방울토마토 | 23.10 kg/m²/년 | 25.0 | 정상 |

**메커니즘**: 일부 농가의 `식부면적`이 오기록(예: 2000 m² 농가가 200으로 기록)되어, `yield_per_m2 = yield_kg / area_m2` 계산 시 10배 이상의 이상치가 발생한다. IQR 클리핑(±1.5 IQR)이 이를 충분히 제거하지 못해 학습 데이터의 평균 자체가 부풀었다.

### 원인 3 (모델 원인 ★★): 5개 작물 모두 CV 성능 부재

| 작물 | CV MAPE | CV R² | 판정 |
|------|---------|-------|------|
| 딸기 | 87.8% | -0.15 | 단순 평균보다 나쁨 |
| 방울토마토 | — | 0.617 | n_train=42 Ridge fallback |
| 완숙토마토 | 139.5% | 0.196 | 예측 불가 수준 |
| 참외 | 71.3% | -0.105 | 단순 평균보다 나쁨 |
| 파프리카 | 127.8% | -0.191 | 단순 평균보다 나쁨 |

모든 작물이 `RDA 상한 클리핑`으로 최대값(12/21/30/12/20 kg/m²)을 출력 중이다.  
실제 농가 수확량이 이보다 낮으면 **그 차이만큼 과대 예측**된다.

---

## 2. 수행된 코드 수정 (P0/P1)

### P0 — 즉시 수정 완료

**① `scripts/train_stage2_yield.py`**  
- `_RDA_YIELD_HARD_CAP` 상수 추가 (작물별 정상 범위 × 2 상한)  
- `_AREA_MIN_M2=100`, `_AREA_MAX_M2=50000` 면적 합리성 범위 추가  
- `load_production_monthly()`: 비정상 면적 → 기본값 교체 + RDA 월별 캡 적용  
- `build_stage2_matrix_annual()`: 비정상 면적 → 기본값 교체 + RDA 연간 캡 적용  

**② `models/m2_yield.py`**  
- `_SEASON_MONTHS` 작기 개월수 맵 추가  
- `predict_yield()` 반환값에 다음 필드 추가:  
  - `yield_kg_m2_monthly`: 월평균 kg/m² (= 연간 ÷ 작기개월)  
  - `season_months`: 사용된 작기 개월수  
  - `unit: "kg/m2/annual"`: 단위 명시  

**③ `models/deployment_gate.py`**  
- `STAGE2_MAPE` 임계값: 40% → **35%** 강화  
- `STAGE2_R2` 임계값: -0.10 → **0.0** 강화  
- 현재 5개 작물 모두 강화 기준으로 탈락 → 통계 블렌딩 전환됨

---

## 3. 작물별 모델 상세 진단

### 딸기 (Strawberry)
- **n_train**: 205 | **모델**: XGB+LGB 앙상블
- **CV R²**: -0.15 (단순 평균보다 나쁨)
- **CV MAPE**: 87.8% — 예측 불신뢰
- **train_rmse**: 8.51 kg/m² — 학습 데이터 내 과적합
- **agg_mode**: annual (연간 집계)
- **개선 우선순위**: ①RDA 캡 후 재학습 ②lag 피처 강화 ③시계열 CV 엄격화

### 방울토마토 (Cherry Tomato)
- **n_train**: 42 (표본 극소!) | **모델**: Ridge fallback
- **CV R²**: 0.617 — 가장 양호하나 n=42로 신뢰도 낮음
- **mape**: 45.5% — 기준 초과
- **agg_mode**: annual_residual — farm_hist_mean 잔차 모드
- **개선 우선순위**: ①데이터 추가 수집(목표 n≥200) ②전이학습 ③RDA 사전확률

### 완숙토마토 (Tomato)
- **n_train**: 177 | **모델**: Ridge (XGB/LGB fallback)
- **CV R²**: 0.196 | **CV MAPE**: 139.5% — 심각
- **train_rmse**: 41.24 kg/m² — global_mean 75.14로 타겟 왜곡
- **agg_mode**: annual
- **개선 우선순위**: ①RDA 캡 후 재학습 (global_mean이 75→20대로 정상화 예상) ②농가별 bias 보정

### 참외 (Melon)
- **n_train**: 84 | **모델**: Ridge
- **CV R²**: -0.105 | **CV MAPE**: 71.3%
- **train_rmse**: 8.24 kg/m² — 정상 범위(3~12) 대비 91% RMSE
- **agg_mode**: annual
- **개선 우선순위**: ①데이터 추가 ②AquaCrop 참외 전용 피처 강화

### 파프리카 (Paprika)
- **n_train**: 112 | **모델**: LGB
- **CV R²**: -0.191 | **CV MAPE**: 127.8% | **gate_pass**: FALSE
- **train_rmse**: 24.30 — global_mean 55.54로 타겟 왜곡
- **agg_mode**: annual | **harvest_lag**: 2개월 (다른 작물과 다름)
- **개선 우선순위**: ①RDA 캡 후 재학습 ②수확 lag 피처 검증

---

## 4. 개선 로드맵 (향후 권장 작업)

### 즉시 (재학습 — 1주 이내)
```bash
# RDA 캡 수정 후 전 작물 재학습
python scripts/train_stage2_yield.py --crop all

# 재학습 후 성능 비교
python analysis/pipeline_trace.py
```

**예상 효과**: 완숙토마토/파프리카의 global_mean이 RDA 정상 범위 내로 정상화 → MAPE 20~50%p 개선 예상

### 단기 (1개월)
- 프론트엔드에서 예측 단위 명시 (`연간 수확량 kg/m²` 레이블 추가)
- `/api/farms/{id}/revenue` 응답에 `unit` 필드 전파
- 방울토마토 학습 데이터 추가 수집 (목표 n_train ≥ 200)

### 중기 (분기)
- Format A/B/C 통합 → `YieldPredictor` 단일 클래스
- 월별 실측 자동 비교 파이프라인 (드리프트 감지)
- 농가별 bias correction 자동화 (`farm_corrections.json` 확장)

---

## 5. 분석 결과 파일 목록

| 파일 | 내용 |
|------|------|
| `analysis/00_analysis_log.md` | 진행 현황 |
| `analysis/01_data_unit_audit.md` | 원시 데이터 단위 감사 |
| `analysis/02_training_pipeline.md` | 학습 파이프라인 감사 |
| `analysis/03_model_performance.md` | 5개 작물 성능 지표 |
| `analysis/04_prediction_pipeline.md` | 예측 파이프라인 추적 |
| `analysis/05_root_cause_10x.md` | 근본 원인 + 개선안 |
| `analysis/FINAL_REPORT.md` | 최종 통합 보고서 (이 파일) |

---

## 수정된 파일 요약

| 파일 | 수정 내용 | 효과 |
|------|----------|------|
| `scripts/train_stage2_yield.py` | RDA 하드 캡 + 면적 검증 추가 | 학습 데이터 이상치 제거 |
| `models/m2_yield.py` | 월별 수치 + 단위 명시 반환 | 10배 오차 인지 개선 |
| `models/deployment_gate.py` | MAPE 35%, R² 0.0으로 강화 | 나쁜 모델 배포 차단 |
