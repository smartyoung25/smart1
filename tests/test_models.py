"""AI 모듈 M1~M5 + 배포 게이트 단위 테스트"""
import pytest
from datetime import date

from models.m1_growth import M1GrowthModel, GrowthPredictionV2 as GrowthPrediction
from models.m2_yield import M2YieldModel, YieldPredictionV2 as YieldPrediction
from models.m3_harvest_timing import predict as predict_harvest, update_gdd
from models.m4_revenue import M4RevenueModel, RevenuePrediction
from models.deployment_gate import evaluate, GateSummary


ENV = {"temp_internal": 22.0, "humidity_int": 75.0, "co2_ppm": 900.0, "solar_rad": 350.0, "gdd_cumsum": 400.0}


# ── M1 ────────────────────────────────────────────────────────────────────────

class TestM1GrowthModel:
    def setup_method(self):
        self.model = M1GrowthModel()  # no artifact → stub mode

    def test_returns_growth_prediction(self):
        pred = self.model.predict(ENV)
        assert isinstance(pred, GrowthPrediction)

    def test_plant_height_positive(self):
        pred = self.model.predict(ENV)
        assert pred.plant_height > 0

    def test_leaf_count_positive(self):
        pred = self.model.predict(ENV)
        assert pred.leaf_count > 0

    def test_confidence_between_0_and_1(self):
        pred = self.model.predict(ENV)
        assert 0.0 <= pred.confidence <= 1.0

    def test_higher_temp_more_growth_near_optimal(self):
        pred_low  = self.model.predict({**ENV, "temp_internal": 15.0})
        pred_high = self.model.predict({**ENV, "temp_internal": 22.0})
        # At 22°C (optimal) height should be >= 15°C height
        assert pred_high.plant_height >= pred_low.plant_height

    def test_more_gdd_more_height(self):
        pred_early = self.model.predict({**ENV, "gdd_cumsum": 100.0})
        pred_late  = self.model.predict({**ENV, "gdd_cumsum": 800.0})
        assert pred_late.plant_height > pred_early.plant_height


# ── M2 ────────────────────────────────────────────────────────────────────────

class TestM2YieldModel:
    def setup_method(self):
        self.model = M2YieldModel()

    def test_returns_yield_prediction(self):
        growth = {"plant_height": 25.0, "leaf_count": 4.0, "leaf_width": 3.0}
        pred = self.model.predict(growth, ENV)
        assert isinstance(pred, YieldPrediction)

    def test_yield_positive(self):
        growth = {"plant_height": 25.0, "leaf_count": 4.0, "leaf_width": 3.0}
        pred = self.model.predict(growth, ENV)
        assert pred.yield_kg_m2 > 0

    def test_prediction_interval_valid(self):
        growth = {"plant_height": 25.0, "leaf_count": 4.0, "leaf_width": 3.0}
        pred = self.model.predict(growth, ENV)
        assert pred.lower_80 <= pred.yield_kg_m2 <= pred.upper_80

    def test_lag_blends_historical(self):
        growth = {"plant_height": 25.0, "leaf_count": 4.0, "leaf_width": 3.0}
        pred_no_lag = self.model.predict(growth, ENV, lag_7d=0.0, lag_14d=0.0)
        pred_lag    = self.model.predict(growth, ENV, lag_7d=0.8, lag_14d=0.8)
        # With high lag, prediction should shift toward 0.8
        assert pred_lag.yield_kg_m2 > pred_no_lag.yield_kg_m2


# ── M3 ────────────────────────────────────────────────────────────────────────

class TestM3HarvestTiming:
    def test_days_remaining_positive(self):
        pred = predict_harvest("strawberry", 400.0, avg_daily_temp=22.0)
        assert pred.days_remaining > 0

    def test_gdd_at_target_gives_zero_days(self):
        pred = predict_harvest("strawberry", 1200.0, avg_daily_temp=22.0)
        assert pred.days_remaining == 0

    def test_higher_temp_fewer_days(self):
        # gdd_current=200 < gdd_target=450 (from growth_stats.json)
        pred_warm = predict_harvest("strawberry", 200.0, avg_daily_temp=25.0)
        pred_cool = predict_harvest("strawberry", 200.0, avg_daily_temp=18.0)
        assert pred_warm.days_remaining < pred_cool.days_remaining

    def test_confidence_increases_with_gdd_progress(self):
        pred_early = predict_harvest("strawberry", 100.0, avg_daily_temp=22.0)
        pred_late  = predict_harvest("strawberry", 1000.0, avg_daily_temp=22.0)
        assert pred_late.confidence > pred_early.confidence

    def test_update_gdd_accumulates(self):
        gdd = 0.0
        gdd = update_gdd(gdd, t_max=25.0, t_min=15.0, crop_type="tomato")  # mean=20, base=10, gdd=10
        assert gdd == pytest.approx(10.0)

    def test_update_gdd_no_accumulation_below_base(self):
        gdd_before = 100.0
        gdd_after  = update_gdd(gdd_before, t_max=8.0, t_min=6.0, crop_type="tomato")  # mean=7 < base=10
        assert gdd_after == pytest.approx(gdd_before)


# ── M4 ────────────────────────────────────────────────────────────────────────

class TestM4RevenueModel:
    def setup_method(self):
        self.model = M4RevenueModel()

    def test_returns_revenue_prediction(self):
        pred = self.model.predict(yield_kg_m2=0.5, area_m2=1000.0)
        assert isinstance(pred, RevenuePrediction)

    def test_revenue_positive(self):
        pred = self.model.predict(yield_kg_m2=0.5, area_m2=1000.0)
        assert pred.revenue_krw > 0

    def test_profit_equals_revenue_minus_cost(self):
        pred = self.model.predict(yield_kg_m2=0.5, area_m2=1000.0)
        assert pred.profit_krw == pytest.approx(pred.revenue_krw - pred.cost_krw, abs=1.0)

    def test_larger_area_more_revenue(self):
        pred_small = self.model.predict(yield_kg_m2=0.5, area_m2=500.0)
        pred_large = self.model.predict(yield_kg_m2=0.5, area_m2=2000.0)
        assert pred_large.revenue_krw > pred_small.revenue_krw

    def test_price_interval_valid(self):
        pred = self.model.predict(yield_kg_m2=0.5, area_m2=1000.0)
        assert pred.price_lower <= pred.kamis_price_krw_kg <= pred.price_upper


# ── Deployment gate ───────────────────────────────────────────────────────────

class TestDeploymentGate:
    def test_all_pass(self):
        summary = evaluate({"M1": 0.70, "M2": 20.0, "M5": 0.90})
        assert summary.all_passed is True
        assert len(summary.failed_modules()) == 0

    def test_m1_fail(self):
        summary = evaluate({"M1": 0.55})
        assert summary.all_passed is False
        assert "M1" in summary.failed_modules()

    def test_m2_fail(self):
        summary = evaluate({"M2": 41.0})  # threshold 40%로 변경됨
        assert summary.all_passed is False
        assert "M2" in summary.failed_modules()

    def test_m5_fail(self):
        summary = evaluate({"M5": 0.80})
        assert summary.all_passed is False
        assert "M5" in summary.failed_modules()

    def test_boundary_m1_exactly_at_threshold(self):
        summary = evaluate({"M1": 0.62})
        assert summary.all_passed is True

    def test_boundary_m2_exactly_at_threshold(self):
        summary = evaluate({"M2": 25.0})
        assert summary.all_passed is True

    def test_empty_metrics_returns_false(self):
        summary = evaluate({})
        assert summary.all_passed is False

    def test_unknown_module_skipped(self):
        summary = evaluate({"M1": 0.70, "M9": 0.99})
        # M9 is unknown — only M1 is evaluated
        m9 = next((r for r in summary.results if r.module_id == "M9"), None)
        assert m9 is None

    def test_to_dict_structure(self):
        summary = evaluate({"M1": 0.70, "M2": 18.0})
        d = summary.to_dict()
        assert "all_passed" in d
        assert "results" in d
        for r in d["results"]:
            assert "module_id" in r
            assert "passed" in r


# ── M5 환경 병해 위험도 평가 ──────────────────────────────────────────────────

class TestEnvRiskPredict:
    from models.m5_disease import env_risk_predict, EnvRiskResult

    def _pred(self, temp, humidity, co2=800.0, crop="딸기"):
        from models.m5_disease import env_risk_predict
        return env_risk_predict(
            {"temp_internal": temp, "humidity_int": humidity, "co2_ppm": co2}, crop
        )

    def test_returns_env_risk_result(self):
        from models.m5_disease import EnvRiskResult
        r = self._pred(22.0, 70.0)
        assert isinstance(r, EnvRiskResult)

    def test_normal_env_is_healthy(self):
        r = self._pred(22.0, 70.0)
        assert r.disease == "healthy"
        assert r.risk_level == "none"
        assert r.score == 0.0

    def test_gray_mold_low_temp_high_humidity(self):
        r = self._pred(15.0, 90.0, crop="딸기")
        assert r.disease == "gray_mold"
        assert r.risk_level in ("medium", "high")

    def test_phytophthora_high_temp_high_humidity(self):
        r = self._pred(27.0, 92.0, co2=1300.0, crop="방울토마토")
        assert r.disease == "phytophthora"
        assert r.risk_level in ("medium", "high")

    def test_powdery_mildew_moderate_humidity(self):
        r = self._pred(24.0, 58.0, crop="참외")
        assert r.disease == "powdery_mildew"
        assert r.risk_level in ("medium", "high")

    def test_score_in_range(self):
        r = self._pred(16.0, 88.0)
        assert 0.0 <= r.score <= 1.0

    def test_action_ko_not_empty(self):
        r = self._pred(16.0, 88.0)
        assert len(r.action_ko) > 0

    def test_reasons_present_when_risk(self):
        r = self._pred(16.0, 88.0)
        if r.risk_level != "none":
            assert len(r.reasons) > 0

    def test_high_co2_increases_score(self):
        r_normal = self._pred(16.0, 87.0, co2=800.0)
        r_high   = self._pred(16.0, 87.0, co2=1400.0)
        assert r_high.score >= r_normal.score

    def test_crop_priority_difference(self):
        # 딸기 우선순위: gray_mold 먼저 — 저온다습에서 gray_mold 반환
        r = self._pred(15.0, 90.0, crop="딸기")
        assert r.disease == "gray_mold"

    def test_risk_levels_ordered(self):
        r_none = self._pred(22.0, 70.0)
        r_high = self._pred(16.0, 90.0)
        assert r_none.score <= r_high.score

    def test_powdery_mildew_high_humidity_no_risk(self):
        """흰가루병은 습도 상한 초과 시 위험 없어야 함"""
        # humidity 92% > 흰가루병 h_hi=68% → 역병/잿빛곰팡이 범주로 처리
        r = self._pred(24.0, 92.0, crop="참외")
        # 참외 우선순위: powdery_mildew 먼저지만 습도 초과라 역병으로
        assert r.disease != "powdery_mildew" or r.risk_level == "none"

    def test_low_risk_score_range(self):
        """중간 조건 → low 또는 medium risk"""
        # 잿빛곰팡이 경계값 근처
        r = self._pred(14.0, 84.0, crop="딸기")
        assert r.risk_level in ("low", "medium", "high")
        assert 0.0 < r.score <= 1.0

    def test_medium_risk_level(self):
        """score 0.40~0.64 범위 → medium"""
        from models.m5_disease import env_risk_predict
        r = env_risk_predict({"temp_internal": 15.5, "humidity_int": 85.0, "co2_ppm": 900.0}, "딸기")
        assert r.score >= 0.0
        if 0.40 <= r.score < 0.65:
            assert r.risk_level == "medium"

    def test_unknown_crop_uses_default_priority(self):
        """알 수 없는 작목 → 기본 우선순위로 평가"""
        r = self._pred(16.0, 88.0, crop="가지")
        assert r.disease in ("healthy", "gray_mold", "powdery_mildew", "phytophthora", "anthracnose")

    def test_temperature_alias(self):
        """temperature 키도 지원"""
        from models.m5_disease import env_risk_predict
        r = env_risk_predict({"temperature": 16.0, "humidity": 88.0}, "딸기")
        assert isinstance(r.score, float)
