"""M4 — 수익 예측 모델 (Prophet + 비용 모델)

입력:
  M2 출력 (yield_kg_m2) + KAMIS 가격 예측 + 운영 비용 파라미터

출력:
  revenue_krw, cost_krw, profit_krw (30일 예측)

배포 게이트: 오차 <= 20%
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional
import logging

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / "artifacts" / "m4_prophet.pkl"
_INCOME_SURVEY_PATH = Path(__file__).parent.parent / "api" / "data" / "income_survey.json"
_SEASON_DAYS = 150   # 표준 작기 일수 (비용 일할 계산 기준)

# 운영비용 기본값 (income_survey.json 없을 때 fallback)
DEFAULT_COST_PARAMS = {
    "labor_per_day_krw":       25_000.0,
    "energy_per_m2_day_krw":   120.0,
    "material_per_m2_day_krw": 30.0,
}


@lru_cache(maxsize=None)
def _load_income_survey() -> dict:
    if not _INCOME_SURVEY_PATH.exists():
        return {}
    try:
        return json.loads(_INCOME_SURVEY_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[M4] income_survey.json load failed: %s", e)
        return {}


def _survey_cost_per_m2_season(crop_ko: str) -> Optional[float]:
    """income_survey.json 작목별 작기당 총 경영비(원/m²). 없으면 None."""
    survey = _load_income_survey()
    costs = survey.get(crop_ko, {}).get("cost_per_m2", {})
    if not costs:
        return None
    total = sum(float(v) for v in costs.values() if isinstance(v, (int, float)))
    return total if total > 0 else None


@dataclass
class RevenuePrediction:
    horizon_days: int
    area_m2: float
    predicted_yield_kg: float
    kamis_price_krw_kg: float
    revenue_krw: float
    cost_krw: float
    profit_krw: float
    confidence: float
    price_lower: float
    price_upper: float


CROP_EN = {
    "딸기":       "strawberry",
    "방울토마토": "cherry_tomato",
    "완숙토마토": "tomato",
    "참외":       "melon",
    "파프리카":   "paprika",
    "오이":       "cucumber",
}

_PROPHET_CACHE: dict = {}


class M4RevenueModel:

    def __init__(self, cost_params=None):
        self._prophet = None
        self._prophet_freq: str = "D"   # "MS" = monthly, "D" = daily
        self._crop_ko: Optional[str] = None
        self._cost = cost_params or dict(DEFAULT_COST_PARAMS)
        self._cost_per_m2_season: Optional[float] = None
        self._mean_price: Optional[float] = None

    @classmethod
    def load_for_crop(cls, crop_ko: str) -> "M4RevenueModel":
        if crop_ko in _PROPHET_CACHE:
            return _PROPHET_CACHE[crop_ko]

        crop_en = CROP_EN.get(crop_ko)
        if crop_en:
            art_dir = MODEL_PATH.parent / crop_en
            pkl_path = art_dir / "price_prophet.pkl"
        else:
            pkl_path = Path("__nonexistent__")

        inst = cls()
        inst._crop_ko = crop_ko

        survey_cost = _survey_cost_per_m2_season(crop_ko)
        if survey_cost is not None:
            inst._cost_per_m2_season = survey_cost
            logger.info("[M4] survey cost: %s = %.0f krw/m2/season", crop_ko, survey_cost)
        else:
            logger.debug("[M4] no survey cost for %s -- using DEFAULT_COST_PARAMS", crop_ko)

        if pkl_path.exists():
            try:
                import pickle
                with open(pkl_path, "rb") as f:
                    bundle = pickle.load(f)
                inst._prophet = bundle.get("prophet")
                inst._prophet_freq = bundle.get("freq", "D")  # "MS" or "D"
                inst._mean_price = bundle.get("mean_price")
                logger.info("[M4] Prophet loaded: %s n=%s mape=%s%% freq=%s",
                            crop_ko, bundle.get("n_train"), bundle.get("train_mape"),
                            inst._prophet_freq)
            except Exception as _e:
                logger.warning("[M4] Prophet load failed (%s) -- stub mode", _e)
        else:
            logger.debug("[M4] no Prophet for %s -- stub mode", crop_ko)

        _PROPHET_CACHE[crop_ko] = inst
        return inst

    def load(self, path: Path = MODEL_PATH) -> "M4RevenueModel":
        if path.exists():
            import pickle
            with open(path, "rb") as f:
                bundle = pickle.load(f)
            self._prophet = bundle.get("prophet")
            self._cost = bundle.get("cost_params", self._cost)
            logger.info("[M4] model loaded from %s", path)
        else:
            logger.warning("[M4] artifact not found -- stub price forecast")
        return self

    def forecast_price(self, horizon_days: int = 30):
        """Return (mean_price, lower_80, upper_80) in KRW/kg.

        월별(freq='MS') 모델: 다음 3개월 예측 평균 반환
        일별(freq='D')  모델: horizon_days 기간 예측 평균 반환
        """
        if self._prophet is not None:
            try:
                if self._prophet_freq == "MS":
                    # 월별 모델 — 3개월 앞 예측 (계절성 반영, 과도 외삽 방지)
                    future = self._prophet.make_future_dataframe(periods=3, freq="MS")
                    fc = self._prophet.predict(future).tail(3)
                else:
                    future = self._prophet.make_future_dataframe(periods=horizon_days)
                    fc = self._prophet.predict(future).tail(horizon_days)
                mean_p  = max(100.0, float(fc["yhat"].mean()))
                lower_p = max(100.0, float(fc["yhat_lower"].mean()))
                upper_p = max(100.0, float(fc["yhat_upper"].mean()))
                # 합리적 범위 클램프 (훈련 평균의 0.25~3배)
                if self._mean_price and self._mean_price > 0:
                    lo_cap = max(100.0, self._mean_price * 0.25)
                    hi_cap = self._mean_price * 3.0
                    mean_p  = max(lo_cap, min(hi_cap, mean_p))
                    lower_p = max(100.0, min(hi_cap, lower_p))
                    upper_p = max(100.0, min(hi_cap * 1.1, upper_p))
                return mean_p, lower_p, upper_p
            except Exception as e:
                logger.warning("[M4] Prophet predict failed(%s) -- stub", e)

        month = date.today().month
        seasonal = {1: 3800, 2: 3600, 3: 3200, 4: 2800, 5: 2600,
                    6: 2400, 7: 2500, 8: 2700, 9: 3000, 10: 3200, 11: 3500, 12: 3700}
        mean = float(seasonal.get(month, 3000))
        return mean, mean * 0.85, mean * 1.15

    def predict_next_month_price(self):
        return self.forecast_price(horizon_days=45)

    def predict(
        self,
        yield_kg_m2: float,
        area_m2: float,
        horizon_days: int = 30,
    ) -> RevenuePrediction:
        total_yield_kg = yield_kg_m2 * area_m2
        mean_price, lower_price, upper_price = self.forecast_price(horizon_days)
        revenue = total_yield_kg * mean_price

        if self._cost_per_m2_season is not None:
            total_cost = self._cost_per_m2_season * area_m2 * (horizon_days / _SEASON_DAYS)
        else:
            labor    = self._cost["labor_per_day_krw"] * horizon_days
            energy   = self._cost["energy_per_m2_day_krw"] * area_m2 * horizon_days
            material = self._cost["material_per_m2_day_krw"] * area_m2 * horizon_days
            total_cost = labor + energy + material

        profit = revenue - total_cost
        confidence = 0.65 if self._prophet is None else 0.78

        return RevenuePrediction(
            horizon_days=horizon_days,
            area_m2=area_m2,
            predicted_yield_kg=round(total_yield_kg, 2),
            kamis_price_krw_kg=round(mean_price, 0),
            revenue_krw=round(revenue, 0),
            cost_krw=round(total_cost, 0),
            profit_krw=round(profit, 0),
            confidence=confidence,
            price_lower=round(lower_price, 0),
            price_upper=round(upper_price, 0),
        )

    def train(
        self,
        price_df: pd.DataFrame,
        cost_params=None,
        save_path: Path = MODEL_PATH,
    ) -> dict:
        """Train Prophet on historical KAMIS prices (ds, y columns)."""
        try:
            from prophet import Prophet
        except ImportError:  # pragma: no cover
            raise RuntimeError("prophet package not installed")

        if cost_params:
            self._cost.update(cost_params)

        m = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=False,
            daily_seasonality=False,
            interval_width=0.80,
        )
        m.fit(price_df[["ds", "y"]])

        future = m.make_future_dataframe(periods=30)
        fc = m.predict(future)
        last_actual = float(price_df["y"].iloc[-1])
        last_pred   = float(fc["yhat"].iloc[-31])
        error_pct   = abs(last_actual - last_pred) / last_actual * 100 if last_actual else 99.0

        save_path.parent.mkdir(parents=True, exist_ok=True)
        import pickle
        with open(save_path, "wb") as f:
            pickle.dump({"prophet": m, "cost_params": self._cost}, f)

        self._prophet = m
        metrics = {"error_pct": round(error_pct, 2), "gate_passed": error_pct <= 20.0}
        logger.info("[M4] trained error=%.2f%% gate=%s", error_pct, metrics["gate_passed"])
        return metrics


_instance: Optional[M4RevenueModel] = None


def get_model() -> M4RevenueModel:
    global _instance
    if _instance is None:
        _instance = M4RevenueModel().load()
    return _instance


def predict(yield_kg_m2: float, area_m2: float, horizon_days: int = 30) -> RevenuePrediction:
    return get_model().predict(yield_kg_m2, area_m2, horizon_days)
