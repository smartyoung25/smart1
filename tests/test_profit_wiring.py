"""수익 계산 배선 회귀 테스트 — 매출/비용/소득이 뒤섞이지 않도록 고정.

배경(2026-07-17 실측 사고 2건):
  ① What-if 가 **매출 델타**를 profit_gain_krw 로 내보내 UI 가 소득으로 오독했다.
     온도를 올리면 매출과 난방비가 함께 오르는데 비용을 빼지 않아, 최적해가 항상
     "온도를 올려라"로 몰렸다. M4CostModel 은 이미 있었으나 연결돼 있지 않았다.
  ② M3 가 학습 피처를 **위치로 슬라이싱**해(X_feat[:, :n]) 개수만 맞으면 틀린 피처를
     조용히 먹였다. 오이·파프리카·완숙·방울은 log_price_annual(연도별 시장가) 자리에
     월별 중앙가가, 참외는 year_trend(0~1) 자리에 float(month)(1~12)가 들어갔다.
     딸기만 개수 불일치로 예외가 나 안전하게 폴백했다 — 실패가 오히려 안전했던 셈.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ARTS = Path(__file__).resolve().parent.parent / "models" / "artifacts"


class TestM3FeatureAlignment:
    """M3 는 학습 피처를 '이름으로' 재구성한다 — 위치 슬라이싱 금지."""

    @pytest.mark.parametrize("crop_ko,crop_en", [
        ("오이", "cucumber"), ("파프리카", "paprika"),
        ("완숙토마토", "tomato"), ("방울토마토", "cherry_tomato"),
    ])
    def test_ridge_applied_when_features_buildable(self, crop_ko, crop_en):
        """2피처 작목은 서빙 시점에 재구성 가능 → Ridge 보정이 실제로 적용돼야 한다."""
        from models.m3_revenue import M3RevenueModel
        p = ARTS / crop_en / "stage3_revenue_coef.pkl"
        if not p.exists():
            pytest.skip(f"{crop_en} stage3 아티팩트 없음")
        m = M3RevenueModel().load(p)
        m.predict(5.0, 7, crop_ko)
        assert m._last_ridge_used is True

    @pytest.mark.parametrize("crop_ko,crop_en", [("딸기", "strawberry"), ("참외", "melon")])
    def test_ridge_skipped_when_features_unbuildable(self, crop_ko, crop_en):
        """재현 불가한 피처(year_trend·farm_price_hist·timing_price)를 쓰는 작목은
        Ridge 를 쓰지 않고 기본 곱셈으로 폴백해야 한다 — 억지로 채우면 조용히 틀린다."""
        from models.m3_revenue import M3RevenueModel
        p = ARTS / crop_en / "stage3_revenue_coef.pkl"
        if not p.exists():
            pytest.skip(f"{crop_en} stage3 아티팩트 없음")
        m = M3RevenueModel().load(p)
        r = m.predict(5.0, 7, crop_ko)
        assert m._last_ridge_used is False
        # 폴백은 '수확량 × 월별 단가' 여야 한다
        assert r.revenue_per_m2 == pytest.approx(5.0 * r.price_used, rel=1e-6)

    def test_never_slices_positionally(self):
        """학습 피처가 만들 수 없는 것뿐이면 Ridge 를 건너뛴다(예외·오예측 대신)."""
        from models.m3_revenue import M3RevenueModel
        m = M3RevenueModel()
        m._loaded = True
        m._ridge = object()                       # predict 가 호출되면 AttributeError
        m._ridge_feature_names = ["year_trend"]   # 서빙에서 만들 수 없는 피처
        r = m.predict(5.0, 7, "딸기")             # 예외 없이 폴백해야 함
        assert m._last_ridge_used is False
        assert r.revenue_per_m2 > 0


class TestM4CostResponds:
    """비용은 온도차와 수확량에 반응해야 한다 — 최적화의 전제."""

    def test_heating_rises_with_temp_gap(self):
        from models.m4_cost import get_cost_model
        cm = get_cost_model()
        lo = cm.predict(month=1, temp_internal=18.0, temp_external=2.0,
                        yield_kg_m2=3.0, crop_ko="딸기")
        hi = cm.predict(month=1, temp_internal=26.0, temp_external=2.0,
                        yield_kg_m2=3.0, crop_ko="딸기")
        assert hi.heating_per_m2 > lo.heating_per_m2
        assert hi.total_per_m2 > lo.total_per_m2

    def test_harvest_labor_rises_with_yield(self):
        from models.m4_cost import get_cost_model
        cm = get_cost_model()
        lo = cm.predict(month=5, temp_internal=22.0, temp_external=18.0,
                        yield_kg_m2=1.0, crop_ko="딸기")
        hi = cm.predict(month=5, temp_internal=22.0, temp_external=18.0,
                        yield_kg_m2=8.0, crop_ko="딸기")
        assert hi.harvest_labor_per_m2 > lo.harvest_labor_per_m2


class TestWhatIfProfitSemantics:
    """profit_gain_krw 는 '소득'이다 — 매출을 소득이라 부르지 않는다."""

    def test_profit_is_revenue_minus_cost(self):
        from api.schemas.farmer import WhatIfResult
        r = WhatIfResult(
            baseline_revenue_krw=1000, whatif_revenue_krw=1500,
            delta_krw=500, delta_pct=50.0, confidence=0.75, model_used="ml_model",
            baseline_cost_krw=300, whatif_cost_krw=500,
            cost_delta_krw=200, profit_delta_krw=300,
            profit_gain_krw=300, revenue_gain_krw=500, revenue_krw=1500,
        )
        # 소득 델타 = 매출 델타 − 비용 델타
        assert r.profit_delta_krw == r.delta_krw - r.cost_delta_krw
        # 별칭은 소득이지 매출이 아니다
        assert r.profit_gain_krw == r.profit_delta_krw
        assert r.revenue_gain_krw == r.delta_krw
        assert r.profit_gain_krw != r.revenue_gain_krw

    def test_cost_fields_optional_when_unavailable(self):
        """비용을 못 구하면 소득을 만들지 않는다 — 매출로 대신 채우지 않는다."""
        from api.schemas.farmer import WhatIfResult
        r = WhatIfResult(
            baseline_revenue_krw=1000, whatif_revenue_krw=1500,
            delta_krw=500, delta_pct=50.0, confidence=0.5, model_used="stats_fallback",
        )
        assert r.profit_delta_krw is None
        assert r.cost_delta_krw is None
        assert r.profit_gain_krw == 0.0      # 매출 델타(500)로 채우면 안 된다
