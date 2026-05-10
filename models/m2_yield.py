"""M2 — 수확량 예측 모델

입력 피처:
  M1 출력 (plant_height, leaf_count, leaf_width) +
  환경 (temp_internal, solar_rad, ec_dsm) +
  시간 피처 (lag_7d_yield, lag_14d_yield)

출력:
  yield_kg_m2 (kg/m²)

배포 게이트: MAPE ≤ 25%
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging
import pickle

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / "artifacts" / "m2_yield.pkl"

FEATURE_COLS = [
    "plant_height", "leaf_count", "leaf_width",
    "temp_internal", "solar_rad", "ec_dsm",
    "lag_7d_yield", "lag_14d_yield",
]


@dataclass
class YieldPrediction:
    yield_kg_m2: float
    confidence: float
    lower_80: float   # 80% prediction interval lower bound
    upper_80: float   # 80% prediction interval upper bound


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true != 0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


class M2YieldModel:

    def __init__(self):
        self._model = None
        self._feature_names: list[str] = []

    def load(self, path: Path = MODEL_PATH) -> "M2YieldModel":
        if path.exists():
            with open(path, "rb") as f:
                bundle = pickle.load(f)
            self._model = bundle["model"]
            self._feature_names = bundle.get("feature_names", FEATURE_COLS)
            logger.info("[M2] model loaded from %s", path)
        else:
            logger.warning("[M2] artifact not found — using stub")
        return self

    def predict(
        self,
        growth: dict[str, float],
        env: dict[str, float],
        lag_7d: float = 0.0,
        lag_14d: float = 0.0,
    ) -> YieldPrediction:
        features = {**growth, **env, "lag_7d_yield": lag_7d, "lag_14d_yield": lag_14d}

        if self._model is not None:
            row = pd.DataFrame([features])
            available = [c for c in self._feature_names if c in row.columns]
            X = row[available].fillna(0.0)
            pred = float(self._model.predict(X)[0])
            margin = pred * 0.15
            return YieldPrediction(
                yield_kg_m2=round(pred, 3),
                confidence=0.72,
                lower_80=round(pred - margin, 3),
                upper_80=round(pred + margin, 3),
            )

        # ── Stub ──
        height = growth.get("plant_height", 20.0)
        ec     = env.get("ec_dsm", 2.0)
        temp   = env.get("temp_internal", 22.0)
        lag    = (lag_7d + lag_14d) / 2 if lag_7d and lag_14d else 0.5

        # Rough heuristic: yield proportional to plant size and nutrient solution
        base = 0.4 + (height - 15) * 0.01 + (ec - 1.5) * 0.05
        temp_factor = 1.0 - abs(temp - 22) * 0.02
        pred = max(0.1, base * temp_factor)
        if lag > 0:
            pred = pred * 0.7 + lag * 0.3   # weighted blend with historical

        margin = pred * 0.20
        return YieldPrediction(
            yield_kg_m2=round(pred, 3),
            confidence=0.55,
            lower_80=round(pred - margin, 3),
            upper_80=round(pred + margin, 3),
        )

    def train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        save_path: Path = MODEL_PATH,
    ) -> dict[str, float]:
        try:
            import xgboost as xgb
            from sklearn.model_selection import train_test_split
        except ImportError as e:
            raise RuntimeError(f"Training dependencies missing: {e}")

        available = [c for c in FEATURE_COLS if c in X.columns]
        X_clean = X[available].fillna(X[available].mean())

        X_tr, X_val, y_tr, y_val = train_test_split(X_clean, y, test_size=0.2, random_state=42)
        model = xgb.XGBRegressor(n_estimators=400, learning_rate=0.04, max_depth=5, random_state=42, n_jobs=-1)
        model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)

        preds = model.predict(X_val)
        mape  = _mape(y_val.values, preds)

        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            pickle.dump({"model": model, "feature_names": available}, f)

        self._model = model
        self._feature_names = available

        metrics = {"mape": round(mape, 2), "gate_passed": mape <= 25.0}
        logger.info("[M2] trained MAPE=%.2f%% gate_passed=%s", mape, metrics["gate_passed"])
        return metrics


_instance: Optional[M2YieldModel] = None


def get_model() -> M2YieldModel:
    global _instance
    if _instance is None:
        _instance = M2YieldModel().load()
    return _instance


def predict(
    growth: dict[str, float],
    env: dict[str, float],
    lag_7d: float = 0.0,
    lag_14d: float = 0.0,
) -> YieldPrediction:
    return get_model().predict(growth, env, lag_7d, lag_14d)
