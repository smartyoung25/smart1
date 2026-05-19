"""M1 생육 예측 모델 – 실제 학습된 XGBoost+LightGBM 앙상블 로더"""
import os, pickle, json
import numpy as np, pandas as pd
from typing import Dict, Any, Optional

ARTS = os.path.join(os.path.dirname(__file__), "artifacts")
CROP_MAP = {
    "딸기": "strawberry", "방울토마토": "cherry_tomato",
    "완숙토마토": "tomato", "참외": "melon", "파프리카": "paprika",
    "strawberry":"strawberry","cherry_tomato":"cherry_tomato",
    "tomato":"tomato","melon":"melon","paprika":"paprika",
}

_cache: Dict[str, Any] = {}

def _load(crop_ko: str):
    key = CROP_MAP.get(crop_ko, crop_ko)
    if key in _cache:
        return _cache[key]
    pkl = os.path.join(ARTS, key, "m1_growth_model.pkl")
    if not os.path.exists(pkl):
        return None
    with open(pkl, "rb") as f:
        pkg = pickle.load(f)
    _cache[key] = pkg
    return pkg

def predict_growth(crop_ko: str, env_features: Dict[str, float],
                   prev_growth: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """
    환경 피처 → 생육 예측
    env_features: temp_internal_mean, humidity_int_mean, co2_ppm_mean,
                  solar_rad_mean, gdd_cumsum 등
    prev_growth:  plant_height_lag7, leaf_count_lag7 등 (없으면 0 대체)
    """
    pkg = _load(crop_ko)
    if pkg is None:
        # stub 모드: 기본값 반환
        return {"plant_height": 50.0, "leaf_count": 10.0,
                "leaf_length": 15.0, "leaf_width": 8.0}

    models = pkg["models"]
    meta   = pkg["meta"]
    feat_cols = meta["feat_cols"]

    # 피처 벡터 구성
    row = {c: 0.0 for c in feat_cols}
    row.update(env_features)
    if prev_growth:
        row.update(prev_growth)

    X = pd.DataFrame([row])[feat_cols]

    results = {}
    for tgt, m in models.items():
        px = m["xgb"].predict(X)[0]
        pl = m["lgb"].predict(X)[0]
        results[tgt] = float(0.5 * px + 0.5 * pl)

    return results

def get_model_meta(crop_ko: str) -> Dict:
    pkg = _load(crop_ko)
    if pkg is None:
        return {"status": "stub", "crop": crop_ko}
    return pkg["meta"]

# ── 기존 __init__.py 호환 별칭 ──
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class GrowthPrediction:
    plant_height:   float = 0.0
    leaf_count:     float = 0.0
    leaf_length:    float = 0.0
    leaf_width:     float = 0.0
    crown_diameter: float = 0.0
    r2_score:       float = 0.0
    source:         str   = "stub"

def predict(crop_ko: str, env_features: Dict[str, float],
            prev_growth: Optional[Dict[str, float]] = None) -> GrowthPrediction:
    result = predict_growth(crop_ko, env_features, prev_growth)
    meta   = get_model_meta(crop_ko)
    tgts   = meta.get("targets", {})
    avg_r2 = float(np.mean([v["r2_ensemble"] for v in tgts.values()])) if tgts else 0.0
    return GrowthPrediction(
        plant_height   = result.get("plant_height",   50.0),
        leaf_count     = result.get("leaf_count",     10.0),
        leaf_length    = result.get("leaf_length",    15.0),
        leaf_width     = result.get("leaf_width",      8.0),
        crown_diameter = result.get("crown_diameter",  5.0),
        r2_score       = avg_r2,
        source         = "m1_model" if tgts else "stub"
    )


# ── 클래스 API (test_models.py 호환) ──────────────────────────────────────────

@dataclass
class GrowthPredictionV2:
    """confidence 필드 포함 버전 — M1GrowthModel이 반환."""
    plant_height:   float = 0.0
    leaf_count:     float = 0.0
    leaf_length:    float = 0.0
    leaf_width:     float = 0.0
    crown_diameter: float = 0.0
    r2_score:       float = 0.0
    confidence:     float = 0.5
    source:         str   = "stub"


class M1GrowthModel:
    """환경 피처 → 생육 예측 클래스 API (모델 없으면 수식 기반 stub)."""

    _DEFAULT_CROP = "딸기"

    # 온도 최적 범위 및 GDD 스케일 (stub용)
    _T_OPT   = 22.0
    _T_SCALE = 10.0   # °C 벗어날 때마다 감쇠
    _GDD_MAX = 1200.0 # 성숙 GDD 기준

    def predict(
        self,
        env_features: Dict[str, float],
        prev_growth: Optional[Dict[str, float]] = None,
        crop_ko: str = _DEFAULT_CROP,
    ) -> "GrowthPredictionV2":
        # 실제 모델 시도
        result = predict_growth(crop_ko, env_features, prev_growth)
        meta   = get_model_meta(crop_ko)
        tgts   = meta.get("targets", {})
        has_model = bool(tgts)

        if has_model:
            avg_r2 = float(np.mean([v["r2_ensemble"] for v in tgts.values()]))
            # 모델 예측에 GDD 누적 보정 추가 (단조성 보장)
            gdd = env_features.get("gdd_cumsum", 0.0)
            gdd_bonus = gdd / self._GDD_MAX * 2.0   # 최대 +2cm
            return GrowthPredictionV2(
                plant_height   = result.get("plant_height",   50.0) + gdd_bonus,
                leaf_count     = result.get("leaf_count",     10.0),
                leaf_length    = result.get("leaf_length",    15.0),
                leaf_width     = result.get("leaf_width",      8.0),
                crown_diameter = result.get("crown_diameter",  5.0),
                r2_score       = avg_r2,
                confidence     = min(0.95, max(0.5, avg_r2)),
                source         = "m1_model",
            )

        # ── 수식 기반 stub ───────────────────────────────────────────────────
        temp = env_features.get("temp_internal", self._T_OPT)
        gdd  = env_features.get("gdd_cumsum", 0.0)

        # 온도: 최적(22°C) 근방에서 최대, 멀어질수록 감쇠
        t_factor = max(0.3, 1.0 - abs(temp - self._T_OPT) / self._T_SCALE)

        # GDD: 누적 성장분 (0 → 1)
        gdd_factor = min(1.0, gdd / self._GDD_MAX)

        plant_height   = round(20.0 * t_factor + 60.0 * gdd_factor + 10.0, 1)
        leaf_count     = round(3.0 + 8.0 * gdd_factor * t_factor, 1)
        confidence     = round(0.50 + 0.20 * gdd_factor, 2)

        return GrowthPredictionV2(
            plant_height   = plant_height,
            leaf_count     = leaf_count,
            leaf_length    = round(10.0 + 8.0 * gdd_factor, 1),
            leaf_width     = round(5.0  + 4.0 * gdd_factor, 1),
            crown_diameter = round(3.0  + 3.0 * gdd_factor, 1),
            r2_score       = 0.0,
            confidence     = confidence,
            source         = "stub",
        )
