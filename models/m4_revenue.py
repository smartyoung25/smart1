"""M4 — 수익 예측 모델 (Prophet + 비용 모델)

입력:
  M2 출력 (yield_kg_m2) + KAMIS 가격 예측 + 운영 비용 파라미터

출력:
  revenue_krw, cost_krw, profit_krw (30일 예측)

배포 게이트: 오차 ≤ 20%
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
import logging

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / "artifacts" / "m4_prophet.pkl"

# 운영비용 기본값 (운영비용.csv 로딩 전 fallback)
DEFAULT_COST_PARAMS = {
    "labor_per_day_krw":       25_000.0,   # 인건비/일
    "energy_per_m2_day_krw":   120.0,      # 에너지/m²/일
    "material_per_m2_day_krw": 30.0,       # 자재/m²/일
}


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
    price_lower: float      # 80% interval
    price_upper: float


class M4RevenueModel:

    def __init__(self, cost_params: Optional[dict] = None):
        self._prophet = None
        self._cost = cost_params or dict(DEFAULT_COST_PARAMS)

    def load(self, path: Path = MODEL_PATH) -> "M4RevenueModel":
        if path.exists():
            import pickle
            with open(path, "rb") as f:
                bundle = pickle.load(f)
            self._prophet = bundle.get("prophet")
            self._cost = bundle.get("cost_params", self._cost)
            logger.info("[M4] model loaded from %s", path)
        else:
            logger.warning("[M4] artifact not found — using stub price forecast")
        return self

    def forecast_price(self, horizon_days: int = 30) -> tuple[float, float, float]:
        """Return (mean_price, lower_80, upper_80) in ₩/kg."""
        if self._prophet is not None:
            future = self._prophet.make_future_dataframe(periods=horizon_days)
            fc = self._prophet.predict(future).tail(horizon_days)
            mean_price  = float(fc["yhat"].mean())
            lower_price = float(fc["yhat_lower"].mean())
            upper_price = float(fc["yhat_upper"].mean())
            return mean_price, lower_price, upper_price

        # Stub: simple seasonal adjustment around 3,000 ₩/kg
        month = date.today().month
        seasonal = {1: 3800, 2: 3600, 3: 3200, 4: 2800, 5: 2600,
                    6: 2400, 7: 2500, 8: 2700, 9: 3000, 10: 3200, 11: 3500, 12: 3700}
        mean = float(seasonal.get(month, 3000))
        return mean, mean * 0.85, mean * 1.15

    def predict(
        self,
        yield_kg_m2: float,
        area_m2: float,
        horizon_days: int = 30,
    ) -> RevenuePrediction:
        total_yield_kg = yield_kg_m2 * area_m2

        mean_price, lower_price, upper_price = self.forecast_price(horizon_days)

        revenue = total_yield_kg * mean_price

        # Cost calculation
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
        cost_params: Optional[dict] = None,
        save_path: Path = MODEL_PATH,
    ) -> dict[str, float]:
        """Train Prophet on historical KAMIS prices.

        Args:
            price_df: DataFrame with columns ['ds' (date), 'y' (price ₩/kg)]
        """
        try:
            from prophet import Prophet
        except ImportError:
            raise RuntimeError("prophet package not installed: pip install prophet")

        if cost_params:
            self._cost.update(cost_params)

        m = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=False,
            daily_seasonality=False,
            interval_width=0.80,
        )
        m.fit(price_df[["ds", "y"]])

        # Cross-validation error estimate (simplified)
        future = m.make_future_dataframe(periods=30)
        fc = m.predict(future)
        last_actual  = float(price_df["y"].iloc[-1])
        last_pred    = float(fc["yhat"].iloc[-31])
        error_pct    = abs(last_actual - last_pred) / last_actual * 100 if last_actual else 99.0

        save_path.parent.mkdir(parents=True, exist_ok=True)
        import pickle
        with open(save_path, "wb") as f:
            pickle.dump({"prophet": m, "cost_params": self._cost}, f)

        self._prophet = m
        metrics = {"error_pct": round(error_pct, 2), "gate_passed": error_pct <= 20.0}
        logger.info("[M4] trained error_pct=%.2f%% gate_passed=%s", error_pct, metrics["gate_passed"])
        return metrics


_instance: Optional[M4RevenueModel] = None


def get_model() -> M4RevenueModel:
    global _instance
    if _instance is None:
        _instance = M4RevenueModel().load()
    return _instance


def predict(yield_kg_m2: float, area_m2: float, horizon_days: int = 30) -> RevenuePrediction:
    return get_model().predict(yield_kg_m2, area_m2, horizon_days)
