# ML 알고리즘 성능 진단 & 고도화 로드맵

> 작성 2026-06-04 · 근거: `models/artifacts/{crop}/*.json` 실측 메타 + 코드 인스펙션

## 1. 성능 현황 (실측)

| 모델 | 알고리즘 | 현 성능 | 게이트 | 판정 |
|------|----------|---------|--------|------|
| **M1 생육** | XGB+LGB 앙상블, feature 69 | R² 전부 음수(−0.20~−0.71), 딸기 stage1만 CV R² 0.284 | R²≥0.62 | 🔴 실패 |
| **M2 수확 legacy v4** | LGB/XGB Optuna(계절단위) | MAPE 54~56%, train R² 0.91~0.99 | MAPE≤35% | 🔴 과적합 |
| **M2 수확 stage2(월집계)** | LGB + 분위수(P10/P90) | 딸기 20.8% / 토마토 28.1% | MAPE≤35% | 🟢 통과 |
| **M3 수확시기** | GDD 공식(비ML) | 미검증 | ±5일 | ⚪ |
| **M4 가격** | Prophet | MAPE 29.9%, CV R² 0.516 | ≤20% | 🟡 |
| **M5 병해** | EfficientNet-B4 + 환경규칙 | F1 게이트 0.88 | F1≥0.88 | 데이터 의존 |

### 작물별 M2 (legacy v4)
| 작물 | MAPE | train R² | n_season | 비고 |
|------|------|----------|----------|------|
| 딸기 | 53.9% | 0.914 | 290 | stage2는 20.8% 통과 |
| 완숙토마토 | 55.7% | 0.921 | 243 | stage2는 28.1% 통과 |
| 방울토마토 | 55.7% | **0.992** | 116 | 과적합(near-perfect train) |
| 파프리카 | 36.5% | 0.870 | 140 | 게이트 1.5%p 초과 |
| 참외 | 27.9% | 0.853 | 59 | 표본 최소 |

## 2. 근본 원인
1. **M1**: 표본(363~1900) 대비 feature 69개 → 다중공선성·과적합 → 음수 R²(평균보다 못함).
2. **M2 이원화**: 계절단위 legacy(실패) ↔ 월집계 stage2(성공)가 공존, 일부 작물이 구버전 사용.
3. **train R² 0.99 ↔ CV MAPE 85~111%**: 고분산 과적합(소표본 59~140 계절).
4. **feature 누락**: VPD·월 주기성·상호작용(온도×습도)·기상예보·환경 변동성 미반영(VPD는 M5에만).
5. **검증**: train 지표로 게이트 판단하는 흔적 → CV 일반화 미보장.

## 3. 고도화 방안

### 🔴 단기 (코드만으로·고확신)
1. **M2 월집계 통일** — legacy v4 폐기, 전 작물 stage2(월 집계+P10/P90 분위수) 채택 → 54%→20~28%.
2. **M1 feature 축소+정규화** — SHAP 상위 ~15개, lag7만, ElasticNet/얕은 LGB(강 reg) → 음수 R² 탈출.
3. **과적합 억제** — max_depth↓·reg↑·n_est↓·early stopping.
4. **검증 체계** — GroupKFold(농장)/TimeSeriesSplit, CV 지표만 게이트.

### 🟡 중기 (데이터 기반)
5. **feature 보강** — VPD, 누적 DLI, 월 sin/cos, 온도×습도, 14일 std.
6. **소표본 계층모델** — 작물군 글로벌 + 작물별 오프셋(hierarchical/transfer), Bayesian prior.
7. **신규 운영기록 활용** — 관수·생육측정·야간 dry-back(이번 세션 적재 시작) 누적 시 입력 feature 편입.
8. **M3 GDD 실측 보정** — 예측 vs 실수확일(50건+), 생식/영양 단계별 GDD 분리.

### 🟢 장기 (구조)
9. 앙상블 스태킹(검증성능 가중 메타러너).
10. 드리프트→자동 재학습 폐루프(CUSUM + retrain_trigger 연동).
11. M5 멀티모달(이미지 CNN + 환경 멀티태스크).

## 4. 권고 실행 순서 (ROI)
```
① M2 전작물 월집계 통일   → 즉시 MAPE 절반 (최대 효과, 데이터 추가 불필요)
② M1 feature 축소+정규화  → 음수 R² → 양수 전환
③ VPD·주기성·상호작용     → M1/M2 동반 개선
④ GroupKFold 검증 체계    → 과적합 재발 방지
```

## 5. 핵심 파일
- 모델: `models/m1_growth.py`·`m2_yield.py`·`m3_harvest_timing.py`·`m4_revenue.py`·`m5_disease.py`
- 학습: `pipeline/train/train_m1.py`·`train_m2.py`(Optuna 60trial)
- 게이트/레지스트리: `models/deployment_gate.py`·`pipeline/model_registry.py`·`retrain_trigger.py`
- 서빙: `api/services/model_loader.py`(4-stage 우선)·`drift_monitor.py`
