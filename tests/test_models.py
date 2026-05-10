"""AI 모듈 M1~M5 + 배포 게이트 단위 테스트"""
import pytest
from datetime import date

from models.m1_growth import M1GrowthModel, GrowthPrediction
from models.m2_yield import M2YieldModel, YieldPrediction
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
        pred_warm = predict_harvest("strawberry", 600.0, avg_daily_temp=25.0)
        pred_cool = predict_harvest("strawberry", 600.0, avg_daily_temp=18.0)
        assert pred_warm.days_remaining < pred_cool.days_remaining

    def test_confidence_increases_with_gdd_progress(self):
        pred_early = predict_harvest("strawberry", 100.0, avg_daily_temp=22.0)
        pred_late  = predict_harvest("strawberry", 1000.0, avg_daily_temp=22.0)
        assert pred_late.confidence > pred_early.confidence

    def test_update_gdd_accumulates(self):
        gdd = 0.0
        gdd = update_gdd(gdd, t_max=25.0, t_min=15.0)  # mean=20, gdd=10
        assert gdd == pytest.approx(10.0)

    def test_update_gdd_no_accumulation_below_base(self):
        gdd_before = 100.0
        gdd_after  = update_gdd(gdd_before, t_max=8.0, t_min=6.0)  # mean=7 < base=10
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
        summary = evaluate({"M2": 30.0})
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
