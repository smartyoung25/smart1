# Section B: 학습 파이프라인 감사
- 분석 시작: 2026-05-23 22:15:18

## 1. 모델 포맷 공존 현황

| 작물 | Format A (m2_yield_model.pkl) | Format C (stage2_yield.pkl) | 4-stage | Stage1 |
|------|-------------------------------|-----------------------------|---------|----|
| 딸기 | ✓ | ✓ | ✓ | ✓ |
| 방울토마토 | ✓ | ✓ | ✓ | ✓ |
| 완숙토마토 | ✓ | ✓ | ✓ | ✓ |
| 참외 | ✓ | ✓ | ✓ | ✓ |
| 파프리카 | ✓ | ✓ | ✓ | ✓ |

### Format A 역변환 감사 (m2_yield_model.pkl)

**딸기**:
  - target=annual, log_transform=True
  - feature_count=13
**방울토마토**:
  - target=annual_residual, log_transform=False
  - feature_count=64
**완숙토마토**:
  - target=annual, log_transform=True
  - feature_count=71
**참외**:
  - target=annual, log_transform=True
  - feature_count=57
**파프리카**:
  - target=annual, log_transform=True
  - feature_count=12

### Format C 역변환 감사 (stage2_yield.pkl)

**딸기**:
  - target=unknown, log_transform=True
  - feature_count=13
  - farm_encoding.global_mean=16.768 → **kg/m² 단위 정상 범위**
**방울토마토**:
  - target=unknown, log_transform=True
  - feature_count=64
  - farm_encoding.global_mean=23.099 → **kg/m² 단위 정상 범위**
**완숙토마토**:
  - target=unknown, log_transform=True
  - feature_count=71
  - farm_encoding.global_mean=75.140 → **kg/m² 단위 정상 범위**
**참외**:
  - target=unknown, log_transform=True
  - feature_count=57
  - farm_encoding.global_mean=16.857 → **kg/m² 단위 정상 범위**
**파프리카**:
  - target=unknown, log_transform=True
  - feature_count=12
  - farm_encoding.global_mean=55.544 → **kg/m² 단위 정상 범위**

## 2. Annual vs Monthly 단위 혼용 추적

| 코드 경로 | 파일 | 반환 단위 | season_months 나눔 |
|---------|------|---------|-----------------|
| m2_yield.predict_yield() | models/m2_yield.py L228 | 연간 kg/m² | ✗ — 연간값 그대로 반환 |
| model_loader._predict_4stage() | api/services/model_loader.py L240 | 연간÷작기개월수 | ✓ — 월간으로 변환 |
| model_loader.predict_season_revenue() | L366 | 총 매출(원) | 월×개월×면적 |

> **결론**: m2_yield.py가 연간값을 반환하는데, 이를 월별 실측과 직접 비교하면 6~10배 차이 발생