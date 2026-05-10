"""M1 — 생육 예측 모델 (XGBoost + LightGBM 앙상블)

입력 피처 (canonical_name 기준):
  temp_internal, humidity_int, co2_ppm, solar_rad, gdd_cumsum

출력:
  plant_height (cm), leaf_count (매), leaf_width (cm)

배포 게이트: R² ≥ 0.62
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import logging
import pickle

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / "artifacts" / "m1_growth.pkl"

FEATURE_COLS = ["temp_internal", "humidity_int", "co2_ppm", "solar_rad", "gdd_cumsum"]
TARGET_COLS  = ["plant_height", "leaf_count", "leaf_width"]

# Optimal ranges for feature engineering
OPTIMAL_TEMP   = 22.0   # °C
OPTIMAL_CO2    = 1000.0 # ppm
OPTIMAL_RH     = 75.0   # %


@dataclass
class GrowthPrediction:
    plant_height: float         # cm
    leaf_count: float           # 매
    leaf_width: float           # cm
    confidence: float           # 0–1
    feature_importance: dict[str, float] = field(default_factory=dict)


def _engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived features to the input DataFrame."""
    out = df.copy()
    if "temp_internal" in out.columns:
        out["temp_deviation"] = (out["temp_internal"] - OPTIMAL_TEMP).abs()
    if "co2_ppm" in out.columns:
        out["co2_bonus"] = (out["co2_ppm"] - 400).clip(lower=0) / 100
    if "humidity_int" in out.columns:
        out["rh_deviation"] = (out["humidity_int"] - OPTIMAL_RH).abs()
    if "gdd_cumsum" in out.columns and "temp_internal" in out.columns:
        out["gdd_rate"] = out["temp_internal"].clip(lower=10) - 10   # base 10°C
    return out


class M1GrowthModel:
    """Wrapper around the trained XGB+LGB ensemble for growth prediction."""

    def __init__(self):
        self._model = None
        self._feature_names: list[str] = []

    def load(self, path: Path = MODEL_PATH) -> "M1GrowthModel":
        if path.exists():
            with open(path, "rb") as f:
                bundle = pickle.load(f)
            self._model = bundle["model"]
            self._feature_names = bundle.get("feature_names", FEATURE_COLS)
            logger.info("[M1] model loaded from %s", path)
        else:
            logger.warning("[M1] model artifact not found at %s — using stub", path)
        return self

    def predict(self, env: dict[str, float]) -> GrowthPrediction:
        """Predict growth metrics from a single environment snapshot."""
        row = pd.DataFrame([env])
        row = _engineer_features(row)

        if self._model is not None:
            available = [c for c in self._feature_names if c in row.columns]
            X = row[available].fillna(row[available].mean())
            preds = self._model.predict(X)[0]
            # preds shape: (3,) = [plant_height, leaf_count, leaf_width]
            confidence = min(0.95, 0.6 + 0.05 * len(available) / len(FEATURE_COLS))
            return GrowthPrediction(
                plant_height=float(preds[0]),
                leaf_count=float(preds[1]),
                leaf_width=float(preds[2]),
                confidence=confidence,
            )

        # ── Stub (no trained model yet) ──
        temp  = env.get("temp_internal", 22.0)
        co2   = env.get("co2_ppm", 900.0)
        solar = env.get("solar_rad", 300.0)
        gdd   = env.get("gdd_cumsum", 200.0)

        temp_bonus  = max(0.0, 1.0 - abs(temp - OPTIMAL_TEMP) * 0.05)
        co2_bonus   = min(1.2, 1.0 + max(0, co2 - 400) / 4000)
        solar_bonus = min(1.1, 1.0 + solar / 5000)

        base_height = 15.0 + gdd * 0.08
        plant_height = base_height * temp_bonus * co2_bonus * solar_bonus
        leaf_count   = max(3.0, plant_height / 6.0)
        leaf_width   = max(2.0, plant_height / 10.0)

        return GrowthPrediction(
            plant_height=round(plant_height, 1),
            leaf_count=round(leaf_count, 1),
            leaf_width=round(leaf_width, 1),
            confidence=0.55,   # stub confidence is below deployment gate
        )

    def train(
        self,
        X: pd.DataFrame,
        y: pd.DataFrame,
        save_path: Path = MODEL_PATH,
    ) -> dict[str, float]:
        """Train XGBoost + LightGBM ensemble and save artifact.

        Returns evaluation metrics dict.
        """
        try:
            import xgboost as xgb
            import lightgbm as lgb
            from sklearn.multioutput import MultiOutputRegressor
            from sklearn.model_selection import train_test_split
            from sklearn.metrics import r2_score
        except ImportError as e:
            raise RuntimeError(f"Training dependencies missing: {e}")

        X_eng = _engineer_features(X)
        feature_names = [c for c in X_eng.columns if c in FEATURE_COLS + ["temp_deviation", "co2_bonus", "rh_deviation", "gdd_rate"]]
        X_clean = X_eng[feature_names].fillna(X_eng[feature_names].mean())

        X_tr, X_val, y_tr, y_val = train_test_split(X_clean, y[TARGET_COLS], test_size=0.2, random_state=42)

        # XGBoost
        xgb_model = MultiOutputRegressor(xgb.XGBRegressor(n_estimators=300, learning_rate=0.05, max_depth=6, random_state=42, n_jobs=-1))
        xgb_model.fit(X_tr, y_tr)
        xgb_preds = xgb_model.predict(X_val)

        # LightGBM
        lgb_model = MultiOutputRegressor(lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=63, random_state=42, n_jobs=-1))
        lgb_model.fit(X_tr, y_tr)
        lgb_preds = lgb_model.predict(X_val)

        # Ensemble (simple average)
        ensemble_preds = (xgb_preds + lgb_preds) / 2.0
        r2 = r2_score(y_val, ensemble_preds)

        class _EnsembleModel:
            def __init__(self, m1, m2):
                self.m1, self.m2 = m1, m2
            def predict(self, X):
                return (self.m1.predict(X) + self.m2.predict(X)) / 2.0

        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            pickle.dump({"model": _EnsembleModel(xgb_model, lgb_model), "feature_names": feature_names}, f)

        self._model = _EnsembleModel(xgb_model, lgb_model)
        self._feature_names = feature_names

        metrics = {"r2": round(r2, 4), "gate_passed": r2 >= 0.62}
        logger.info("[M1] trained R²=%.4f gate_passed=%s", r2, metrics["gate_passed"])
        return metrics


# Module-level singleton
_instance: Optional[M1GrowthModel] = None


def get_model() -> M1GrowthModel:
    global _instance
    if _instance is None:
        _instance = M1GrowthModel().load()
    return _instance


def predict(env: dict[str, float]) -> GrowthPrediction:
    return get_model().predict(env)
