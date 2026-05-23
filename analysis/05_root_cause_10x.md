# Section E: 10배 오차 근본 원인 + 개선안

**분석 완료**: 2026-05-23  
**결론**: 복합 원인 3가지 확정

---

## 핵심 증거 요약

| 항목 | 수치 | 판정 |
|------|------|------|
| pipeline_trace 딸기 예측 | 12.0 kg/m²/**연간** | RDA 상한(12.0) 클리핑됨 |
| 사용자가 보는 실측 | ~1.0~2.0 kg/m²/**월별** | 연간환산 6~12 kg/m² |
| farm_encoding.global_mean (완숙토마토) | **75.14** kg/m² | RDA 기준(8~30) 대비 2.5배 초과 |
| farm_encoding.global_mean (파프리카) | **55.54** kg/m² | RDA 기준(8~20) 대비 2.8배 초과 |
| 5개 작물 모두 RDA 상한 클리핑 | 12/21/30/12/20 | 모델이 과대 예측 중 |
| 총출하량 CSV 중앙값 | 63.8 (일별) | kg 단위 정상 (일별 데이터이므로 당연) |
| 식부면적 CSV 중앙값 | 1600.0 m² | m² 단위 정상 |

---

## 원인 1 (★★★ 가장 직접적) — 연간 예측값을 월별 실측과 비교

### 증거
- `m2_yield.py`의 `predict_yield()` 반환값: **연간** kg/m²
  - 딸기 예측: **12.0 kg/m²/년**
  - 사용자 측정: 월별 수확량 → **1.0~2.0 kg/m²/월**
  - 직접 비교 시: 12.0 vs 1.0~2.0 = **6~12배 차이**
- `model_loader.py`의 `_predict_4stage()`는 `/season_months`로 나눔 → 월별 반환
- `m2_yield.py`는 나누지 않음 → 연간값 그대로 반환
- 두 코드 경로가 **다른 단위**를 반환하므로 혼용 시 10배 오차 발생

### 메커니즘
```
사용자 실측 기록: 2월 수확 1.5 kg/m² (월별)
모델 예측 호출:   predict_yield("딸기") → 12.0 kg/m²  (연간!)
직접 비교:        12.0 / 1.5 = 8배 차이 ← "10배 차이"의 직접 원인
```

### 수정
- `predict_yield()` 반환 dict에 `unit: "kg/m2/annual"` 명시
- 프론트엔드/API 비교 시 연간÷작기개월수 적용
- `m2_yield.py`에 `yield_kg_m2_monthly` 필드 추가

---

## 원인 2 (★★★ 학습 데이터 오염) — 면적 아웃라이어로 인한 yield_per_m2 과대

### 증거
- `farm_encoding.global_mean` (학습 데이터 평균 수확량):
  - 완숙토마토: **75.14 kg/m²/년** — 물리적 가능 범위 상한(30) 대비 2.5배
  - 파프리카: **55.54 kg/m²/년** — RDA 상한(20) 대비 2.8배
  - 딸기: 16.77 — RDA 상한(12) 대비 1.4배
- 이는 **학습 타겟이 실제보다 1.4~2.8배 부풀려진** 것을 의미
- 모델이 이 부풀린 타겟을 학습 → 예측값도 과대

### 메커니즘
```python
# 소규모 오기록 농가 예시
yield_kg = 15,000  # 연간 수확량 (정상)
area_m2 = 200      # 실제 2000 m²이지만 200으로 오기록 (한 자리 오탈자)
yield_per_m2 = 15000 / 200 = 75.0  # ← 비정상적으로 높은 값

# IQR 클리핑 (현재 2%~98%)으로는 제거 안 됨
# → 학습 데이터에 포함 → global_mean 상승 → 모델 편향
```

### 수정
- 학습 전 **RDA 기준 하드 클리핑** 추가 (IQR 대신 또는 병행):
  ```python
  # train_stage2_yield.py에 추가
  RDA_HARD_CAP = {"딸기": 15.0, "완숙토마토": 40.0, "파프리카": 25.0, ...}
  df["yield_per_m2"] = df["yield_per_m2"].clip(upper=RDA_HARD_CAP[crop])
  ```
- 면적 합리성 검증: `area_m2 < 100` 또는 `area_m2 > 50000`이면 경고 + 제외

---

## 원인 3 (★★) — 3개 모델 포맷 혼재로 역변환 불일치

### 증거
- Format A (`m2_yield_model.pkl`): 각 작물마다 존재 (5/5)
- Format C (`stage2_yield.pkl`): 각 작물마다 존재 (5/5)
- **두 포맷이 모두 존재하면 Format C가 우선 적용** (m2_yield.py L93 조건)
- Format A (target=`log_yield_ratio`): `expm1(pred) × farm_mean` → 단위가 farm_mean에 의존
- Format C (target=`log1p(yield_per_m2)`): `expm1(pred) × area_m2` → 연간 kg

### 수정
- Format A (`m2_yield_model.pkl`) 폐기 또는 Format C와 통합
- 단일 `YieldPredictor` 클래스로 표준화

---

## 원인 4 (★★) — 게이팅 기준 과도하게 관대

### 증거
- 현재 gate 조건: `MAPE ≤ 40% OR R² ≥ 0.0`
- 통과한 모델 품질:
  - 딸기: CV MAPE=87.8%, CV R²=-0.15 → **통과** (train MAPE=50.2% 기준)
  - 완숙토마토: CV MAPE=139.5% → **통과** (R²=0.196 기준)
- 엄격 기준(MAPE≤30% AND R²≥0.10) 적용 시 **5개 작물 전부 탈락**

### 수정
- Gate 강화: `MAPE ≤ 35% AND R² ≥ 0.10`
- gate_pass=False 시 통계 기반 블렌딩 비율 상향 (ML→통계 전환)
- 월별 실측 자동 비교 모니터링 파이프라인 추가

---

## 종합 개선 로드맵

### 즉시 수정 (P0 — 1일 이내)
1. `models/m2_yield.py`: 반환 dict에 `unit`, `period`, `yield_kg_m2_monthly` 추가
2. `scripts/train_stage2_yield.py`: RDA 하드 캡 클리핑 추가 (IQR 전에 적용)
3. `scripts/train_stage2_yield.py`: 면적 합리성 검증 추가

### 단기 수정 (P1 — 1주 이내)
4. `models/deployment_gate.py`: Gate 기준 강화
5. API 엔드포인트: 반환값에 unit 필드 추가
6. 프론트엔드: 연간/월별 토글 표시 수정

### 중기 수정 (P2 — 1개월 이내)
7. 전 작물 재학습 (RDA 클리핑 적용 후)
8. Format A/B/C 통합 리팩터링
9. 월별 실측 자동 수집 + 예측 vs 실측 대시보드

### 장기 수정 (P3 — 분기 단위)
10. 외부 RDA 통계 기반 사전확률 모델 (베이지안 접근)
11. 작목별 전문 피처 엔지니어링 고도화
12. 농가별 교정(calibration) 모델 자동화
