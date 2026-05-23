# Section D: 예측 파이프라인 추적
- 분석 시작: 2026-05-24 03:41:28

## 1. Format A/C vs 4-stage 결과 비교

테스트 환경: temp=18.0°C, humidity=72.0%, CO₂=800.0ppm
테스트 면적: 1200.0 m², farm_id=farm_003

| 작물 | Format-A/C yield_kg_m² | RDA기대값 | 비율(예측/기대) | source | 4stage revenue(원/m²/월) |
|------|----------------------|---------|--------------|-------|------------------------|
| 딸기 | 9.7269 | 5.0 | 1.9× 정상 | m2_stage2_blended | 5458 |
| 방울토마토 | 14.3506 | 12.0 | 1.2× 정상 | m2_stage2_blended | 4560 |
| 완숙토마토 | 18.4198 | 18.0 | 1.0× 정상 | m2_stage2_blended | 19268 |
| 참외 | 14.47 | 7.0 | 2.1× ⚠ 2배 이상 이상 | m2_stage2_blended | 5 |
| 파프리카 | 10.0217 | 14.0 | 0.7× 정상 | m2_stage2 | 3605 |

## 2. Annual vs Monthly 혼용 시 예상 오차

| 작물 | 연간 예측(kg/m²) | 월별 환산(÷개월) | 실측 월별 기대값 | 비율 |
|------|--------------|-------------|-------------|-----|
| 딸기 | 9.73 | 1.621 (÷6) | 0.833 | 1.9× |
| 방울토마토 | 14.35 | 1.794 (÷8) | 1.500 | 1.2× |
| 완숙토마토 | 18.42 | 2.302 (÷8) | 2.250 | 1.0× |
| 참외 | 14.47 | 3.618 (÷4) | 1.750 | 2.1× |
| 파프리카 | 10.02 | 1.002 (÷10) | 1.400 | 0.7× |

> 예측이 연간, 실측 비교가 월별이면 위 비율만큼 차이 발생

## 3. 역변환 경로 코드 추적 요약

### Format A (m2_yield_model.pkl, target=log_yield_ratio)
```python
# models/m2_yield.py L84-88
if tgt == 'log_yield_ratio':
    farm_mean = row.get('farm_yield_mean', 5000.0)  # ← 단위 불명확!
    yield_total = float(np.expm1(log_pred) * farm_mean)
    # farm_mean이 kg이면 yield_total = 연간 총 kg ✓
    # farm_mean이 kg/m²이면 yield_total = 매우 작은 값 ✗
```

### Format C (stage2_yield.pkl, target=log1p(yield_per_m2_annual))
```python
# models/m2_yield.py L149-151
elif log_transform:
    yield_total = float(np.expm1(max(log_pred, 0))) * max(area_m2, 1)
    # → yield_total = 연간 총 kg
    # → yield_m2 = yield_total / area_m2 = 연간 kg/m² ← 이것이 사용자가 보는 값
```

### 4-stage (stage2_yield.pkl + stage3_revenue_coef.pkl)
```python
# api/services/model_loader.py L180-240
yield_per_m2 = float(np.expm1(raw))           # 연간 kg/m²
revenue_annual = float(np.expm1(ridge.predict(...)[0]))  # 연간 원/m²
revenue_monthly = revenue_annual / season_months  # ← 월별 원/m² 반환
```

## 4. 액션 아이템

- [ ] Format A `farm_yield_mean` 단위 확인 — 연간 총 kg인지 kg/m²인지
- [ ] 예측값 반환 시 단위 명시 (`unit: 'kg/m2/annual'`) 추가
- [ ] 프론트엔드/API 비교 시 동일 단위(연간 or 월별) 통일 확인
- [ ] m2_yield.py Format A/B/C 단일 경로로 통합