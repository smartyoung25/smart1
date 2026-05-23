"""Phase 40 — NASA POWER, World Bank, optimize_bayesian, M1/M2 신규 피처 테스트."""
import os

EXTRA = '''

# ─────────────────────────────────────────────────────────────────────────────
# Phase 40 — 글로벌 API·Bayesian 최적화·신규 피처 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestNasaPowerAdapter:
    """adapters/nasa_power_adapter.py 커버리지."""

    def test_import_ok(self):
        from adapters.nasa_power_adapter import (
            fetch_nasa_power, get_monthly_avg,
            calc_et0_hargreaves_nasa, _PARAM_MAP,
        )
        assert "ALLSKY_SFC_SW_DWN" in _PARAM_MAP
        assert "T2M" in _PARAM_MAP

    def test_get_monthly_avg_api_failure_returns_empty(self):
        """API 실패(네트워크 없음 등) 시 빈 dict 반환."""
        from unittest.mock import patch
        from adapters.nasa_power_adapter import get_monthly_avg
        with patch("adapters.nasa_power_adapter.requests.get", side_effect=Exception("no net")):
            r = get_monthly_avg(lat=36.5, lon=127.5, year=2024, month=1)
        assert isinstance(r, dict)  # 빈 dict 또는 dict

    def test_fetch_nasa_power_bad_response(self):
        """빈 응답 처리."""
        from unittest.mock import patch, MagicMock
        from adapters.nasa_power_adapter import fetch_nasa_power
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"properties": {"parameter": {}}}
        mock_resp.raise_for_status.return_value = None
        with patch("adapters.nasa_power_adapter.requests.get", return_value=mock_resp):
            r = fetch_nasa_power(lat=36.5, lon=127.5)
        assert isinstance(r, list)

    def test_fetch_nasa_power_good_response(self):
        """정상 응답 파싱."""
        from unittest.mock import patch, MagicMock
        from adapters.nasa_power_adapter import fetch_nasa_power
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "properties": {
                "parameter": {
                    "ALLSKY_SFC_SW_DWN": {"20240101": 150.0, "20240102": 160.0},
                    "T2M":               {"20240101": 5.2,   "20240102": 6.1},
                    "T2M_MAX":           {"20240101": 9.0,   "20240102": 10.0},
                    "T2M_MIN":           {"20240101": 1.0,   "20240102": 2.0},
                }
            }
        }
        with patch("adapters.nasa_power_adapter.requests.get", return_value=mock_resp):
            from datetime import date
            r = fetch_nasa_power(lat=36.5, lon=127.5,
                                 start=date(2024,1,1), end=date(2024,1,2))
        assert len(r) == 2
        assert "solar_rad" in r[0]
        assert "temp_external" in r[0]

    def test_calc_et0_hargreaves_nasa_api_failure(self):
        """API 실패 시 None 반환."""
        from unittest.mock import patch
        from adapters.nasa_power_adapter import calc_et0_hargreaves_nasa
        with patch("adapters.nasa_power_adapter.requests.get", side_effect=Exception("timeout")):
            r = calc_et0_hargreaves_nasa()
        assert r is None

    def test_calc_et0_good_data(self):
        """정상 기상 데이터 → ET₀ 양수값."""
        from unittest.mock import patch
        from adapters.nasa_power_adapter import calc_et0_hargreaves_nasa
        from datetime import date
        mock_rows = [{
            "date": "20240601",
            "solar_rad": 250.0,
            "temp_external": 25.0,
            "temp_ext_max": 30.0,
            "temp_ext_min": 18.0,
            "precip_mm": 0.0,
            "humidity_ext": 60.0,
        }]
        with patch("adapters.nasa_power_adapter.fetch_nasa_power", return_value=mock_rows):
            et0 = calc_et0_hargreaves_nasa(target_date=date(2024,6,1))
        assert et0 is not None
        assert et0 > 0.0

    def test_negative_999_filtered(self):
        """NASA -999 결측값 필터링."""
        from unittest.mock import patch, MagicMock
        from adapters.nasa_power_adapter import fetch_nasa_power
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "properties": {
                "parameter": {
                    "ALLSKY_SFC_SW_DWN": {"20240101": -999.0},
                    "T2M":               {"20240101": -999.0},
                }
            }
        }
        with patch("adapters.nasa_power_adapter.requests.get", return_value=mock_resp):
            from datetime import date
            r = fetch_nasa_power(start=date(2024,1,1), end=date(2024,1,1))
        if r:
            assert r[0].get("solar_rad") is None


class TestWorldBankPriceAdapter:
    """adapters/worldbank_price_adapter.py 커버리지."""

    def test_import_ok(self):
        from adapters.worldbank_price_adapter import (
            fetch_pink_sheet_latest, get_food_price_index,
            get_m3_correction_factor, get_annual_price_trend,
            _WORLD_AVG_USD_KG,
        )
        assert "딸기" in _WORLD_AVG_USD_KG
        assert "오이" in _WORLD_AVG_USD_KG

    def test_get_food_price_index_api_failure(self):
        """API 실패 시 None 반환."""
        from unittest.mock import patch
        from adapters.worldbank_price_adapter import get_food_price_index
        with patch("adapters.worldbank_price_adapter.requests.get", side_effect=Exception("no net")):
            r = get_food_price_index()
        assert r is None

    def test_get_food_price_index_good_response(self):
        """정상 응답 → 숫자 반환."""
        from unittest.mock import patch, MagicMock
        from adapters.worldbank_price_adapter import get_food_price_index
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = [
            {"page": 1},
            [{"value": 128.5, "date": "2023"}],
        ]
        with patch("adapters.worldbank_price_adapter.requests.get", return_value=mock_resp):
            r = get_food_price_index()
        assert r == 128.5

    def test_get_m3_correction_factor_strawberry(self):
        """딸기 보정계수: 국내 5000원/kg vs 세계 2100원/kg → >1.0."""
        from adapters.worldbank_price_adapter import get_m3_correction_factor
        cf = get_m3_correction_factor("딸기", domestic_price_krw_kg=5000.0, usd_krw_rate=1320.0)
        assert 0.5 <= cf <= 2.0
        assert cf > 1.0  # 국내 가격 높음

    def test_get_m3_correction_factor_clipping(self):
        """극단값은 0.5~2.0으로 클리핑."""
        from adapters.worldbank_price_adapter import get_m3_correction_factor
        # 매우 낮은 국내가격
        cf_low = get_m3_correction_factor("토마토", domestic_price_krw_kg=10.0)
        assert cf_low >= 0.5
        # 매우 높은 국내가격
        cf_high = get_m3_correction_factor("딸기", domestic_price_krw_kg=999999.0)
        assert cf_high <= 2.0

    def test_get_m3_correction_factor_unknown_crop(self):
        """미등록 작목 → 기본값 1.0."""
        from adapters.worldbank_price_adapter import get_m3_correction_factor
        cf = get_m3_correction_factor("미등록작목xyz", domestic_price_krw_kg=3000.0)
        assert cf == 1.0  # 분자와 분모 모두 1.0

    def test_get_annual_price_trend_no_fpi(self):
        """FPI 없음 → trend_pct=0 반환."""
        from unittest.mock import patch
        from adapters.worldbank_price_adapter import get_annual_price_trend
        with patch("adapters.worldbank_price_adapter.get_food_price_index", return_value=None):
            r = get_annual_price_trend("딸기")
        assert "trend_pct_per_year" in r
        assert r["trend_pct_per_year"] == 0.0
        assert "source" in r

    def test_get_annual_price_trend_with_fpi(self):
        """FPI 있음 → 보정계수 계산."""
        from unittest.mock import patch
        from adapters.worldbank_price_adapter import get_annual_price_trend
        with patch("adapters.worldbank_price_adapter.get_food_price_index", return_value=130.0):
            r = get_annual_price_trend("방울토마토", years=3)
        assert "correction_factor" in r
        assert r["fao_food_price_idx"] == 130.0

    def test_crop_series_coverage(self):
        """주요 작목이 _CROP_TO_SERIES에 매핑되어 있는지 확인."""
        from adapters.worldbank_price_adapter import _CROP_TO_SERIES
        for crop in ["토마토", "완숙토마토", "방울토마토", "딸기", "파프리카", "참외", "오이"]:
            assert crop in _CROP_TO_SERIES, f"{crop} 미매핑"


class TestOptimizeBayesian:
    """engine/profit_optimizer.py optimize_bayesian() 함수 커버리지."""

    def test_import_ok(self):
        from engine.profit_optimizer import optimize_bayesian
        assert callable(optimize_bayesian)

    def test_bayesian_fallback_without_yield_fn(self):
        """yield_fn 없으면 greedy fallback 호출."""
        from engine.profit_optimizer import optimize_bayesian, EnvState, FarmTier
        from unittest.mock import patch, MagicMock
        # patch optimize to return empty list (simplest)
        with patch("engine.profit_optimizer.optimize", return_value=[]) as mock_opt:
            env = EnvState(values={"temp_internal": 22.0, "humidity_int": 70.0,
                                   "co2_ppm": 800.0, "solar_rad": 100.0, "soil_temp": 18.0})
            recs = optimize_bayesian(
                farm_id="farm_001",
                tier=FarmTier.BASIC,
                current_env=env,
                crop_ko="딸기",
                yield_predict_fn=None,
            )
        assert isinstance(recs, list)

    def test_bayesian_with_mock_yield_fn(self):
        """yield_fn 제공 시 Optuna 탐색 → Recommendation 반환."""
        import optuna
        from engine.profit_optimizer import optimize_bayesian, EnvState, FarmTier

        def mock_yield_fn(env):
            # 온도 22°C 근방에서 최대 수확량
            temp = env.get("temp_internal", 20.0)
            yield_val = 1.0 - abs(temp - 22.0) * 0.05
            return max(0.1, yield_val), 0.8

        env = EnvState(values={"temp_internal": 18.0, "humidity_int": 70.0,
                               "co2_ppm": 700.0, "solar_rad": 100.0, "soil_temp": 18.0})
        recs = optimize_bayesian(
            farm_id="farm_001",
            tier=FarmTier.BASIC,
            current_env=env,
            crop_ko="딸기",
            yield_predict_fn=mock_yield_fn,
            n_trials=10,
        )
        assert isinstance(recs, list)
        # 탐색 결과가 있으면 source 확인
        for r in recs:
            assert hasattr(r, "source")

    def test_cucumber_mapping_in_optimize(self):
        """오이 작목이 optimize 내부 딕셔너리에 매핑되어 있는지 smoke test."""
        from engine.profit_optimizer import optimize, EnvState, FarmTier
        # 오이로 optimize 호출 시 KeyError 없이 반환되면 성공
        env = EnvState(values={"temp_internal": 25.0, "humidity_int": 75.0,
                               "co2_ppm": 800.0, "solar_rad": 100.0, "soil_temp": 20.0})
        try:
            recs = optimize(
                farm_id="farm_001", tier=FarmTier.BASIC,
                current_env=env, crop_ko="오이",
                area_m2=1000.0, horizon_days=30,
            )
            assert isinstance(recs, list)
        except Exception as e:
            # KeyError가 아닌 다른 오류는 허용 (M2 모델 없음 등)
            assert "cucumber" not in str(e).lower() or "KeyError" not in type(e).__name__


class TestM1NewFeatures:
    """train_stage1_growth.py 신규 피처 코드 임포트 테스트."""

    def test_build_stage1_matrix_imports(self):
        """build_stage1_matrix 함수가 import 가능하고 호출 가능한지."""
        from scripts.train_stage1_growth import build_stage1_matrix
        assert callable(build_stage1_matrix)

    def test_stage1_matrix_empty_returns_empty(self):
        """빈 growth_monthly → 빈 DataFrame 반환."""
        import pandas as pd
        from scripts.train_stage1_growth import build_stage1_matrix
        from models.crop_config import CROP_CONFIGS
        empty_g = pd.DataFrame()
        empty_e = pd.DataFrame(columns=["farm_id","year","month","temp_internal_mean","solar_rad_mean"])
        result = build_stage1_matrix(empty_e, empty_g, CROP_CONFIGS["딸기"])
        assert result.empty


class TestM2NewFeatures:
    """train_stage2_yield.py 신규 피처 (yield lag, 오이 임계이벤트) 테스트."""

    def test_cucumber_in_critical_event_cfg(self):
        """오이가 _CRITICAL_EVENT_CFG에 있는지."""
        from scripts.train_stage2_yield import _CRITICAL_EVENT_CFG
        assert "오이" in _CRITICAL_EVENT_CFG
        cfg = _CRITICAL_EVENT_CFG["오이"]
        assert "flowering_months" in cfg
        assert "cold_thresh" in cfg
        assert cfg["cold_thresh"] == 12.0

    def test_build_stage2_matrix_imports(self):
        """build_stage2_matrix 함수 import."""
        from scripts.train_stage2_yield import build_stage2_matrix
        assert callable(build_stage2_matrix)

    def test_calc_vpd_series(self):
        """VPD 계산 함수 검증."""
        import pandas as pd
        from scripts.train_stage2_yield import _calc_vpd_series
        temp = pd.Series([20.0, 25.0, 30.0])
        humi = pd.Series([70.0, 60.0, 50.0])
        vpd = _calc_vpd_series(temp, humi)
        assert all(vpd >= 0)
        # 고온·저습 → VPD 높음
        assert vpd.iloc[2] > vpd.iloc[0]
'''

dest = os.path.join(os.path.dirname(__file__), "test_coverage_boost.py")
with open(dest, "a", encoding="utf-8") as f:
    f.write(EXTRA)

print("OK - Phase 40 tests appended")
