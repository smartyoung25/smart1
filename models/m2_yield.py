"""M2 수확량 예측 v2 – log_yield / log_yield_ratio 자동 감지 + 농가별 bias correction"""
import os, pickle, json
import numpy as np, pandas as pd
from typing import Dict, Any, Optional
from dataclasses import dataclass

ARTS = os.path.join(os.path.dirname(__file__), "artifacts")
CROP_MAP = {
    "딸기":"strawberry","방울토마토":"cherry_tomato","완숙토마토":"tomato",
    "참외":"melon","파프리카":"paprika",
    "strawberry":"strawberry","cherry_tomato":"cherry_tomato",
    "tomato":"tomato","melon":"melon","paprika":"paprika",
}
_cache: Dict[str, Any] = {}
_corr_cache: Dict[str, Any] = {}

def _load(crop_ko: str):
    key = CROP_MAP.get(crop_ko, crop_ko)
    if key in _cache: return _cache[key]
    pkl = os.path.join(ARTS, key, "m2_yield_model.pkl")
    if not os.path.exists(pkl): return None
    with open(pkl, "rb") as f: pkg = pickle.load(f)
    _cache[key] = pkg
    return pkg

def _load_corrections(crop_ko: str) -> Dict[str, Any]:
    """Load per-farm bias correction factors. Returns empty dict if not found."""
    key = CROP_MAP.get(crop_ko, crop_ko)
    if key in _corr_cache: return _corr_cache[key]
    path = os.path.join(ARTS, key, "farm_corrections.json")
    if not os.path.exists(path):
        _corr_cache[key] = {}
        return {}
    try:
        data = json.loads(open(path, encoding="utf-8").read())
        _corr_cache[key] = data.get("corrections", {})
    except Exception:
        _corr_cache[key] = {}
    return _corr_cache[key]

def predict_yield(crop_ko: str, season_env: Dict[str, float],
                  area_m2: float = 1000.0,
                  farm_id: Optional[str] = None) -> Dict[str, float]:
    pkg = _load(crop_ko)
    if pkg is None:
        return {"yield_kg_total":5000.0,"yield_kg_m2":5.0,"source":"stub"}

    # ── 포맷 감지 ─────────────────────────────────────────────────────────────
    # 포맷 A (train_stage2_yield.py): feat_cols, feat_median, target, farm_yield_mean
    # 포맷 B (continuous_learning_dag retrain_m2): features, log_transform, cv_mape
    if "feat_cols" in pkg:
        # ── 포맷 A ────────────────────────────────────────────────────────────
        feat_cols = pkg["feat_cols"]
        med       = pkg.get("feat_median", {})
        tgt       = pkg.get("target", "log_yield")

        row = {c: med.get(c, 0.0) for c in feat_cols}
        row.update(season_env)
        if "log_area" in feat_cols:
            row["log_area"] = float(np.log1p(area_m2))

        farm_mean_map = pkg.get("farm_yield_mean", {})
        if "farm_yield_mean" in feat_cols:
            if farm_id and farm_id in farm_mean_map:
                row["farm_yield_mean"] = float(farm_mean_map[farm_id])
            else:
                row["farm_yield_mean"] = (
                    float(np.median(list(farm_mean_map.values())))
                    if farm_mean_map else 5000.0
                )
        if "farm_yield_std" in feat_cols:
            row["farm_yield_std"] = (
                float(np.std(list(farm_mean_map.values())))
                if farm_mean_map else 2000.0
            )
        if "farm_n" in feat_cols:
            row["farm_n"] = 3.0

        X = pd.DataFrame([row])[feat_cols]
        px = pkg["xgb"].predict(X)[0]
        pl = pkg["lgb"].predict(X)[0]
        log_pred = 0.5 * (px + pl)

        if tgt == "log_yield_ratio":
            farm_mean  = row.get("farm_yield_mean", 5000.0)
            yield_total = float(np.expm1(log_pred) * farm_mean)
        else:
            yield_total = float(np.expm1(max(log_pred, 0)))

        mape_cv = pkg.get("mape", 99)
        source  = "m2_model_v2"

    else:
        # ── 포맷 B (DAG retrain_m2) ───────────────────────────────────────────
        feat_cols     = pkg.get("features", [])
        log_transform = pkg.get("log_transform", True)

        if not feat_cols:
            return {"yield_kg_total": 5000.0, "yield_kg_m2": 5.0, "source": "stub"}

        # 누락 피처는 0으로 패딩
        row = {c: 0.0 for c in feat_cols}
        row.update(season_env)

        X = pd.DataFrame([row])[feat_cols]
        preds = []
        if pkg.get("xgb") is not None:
            preds.append(pkg["xgb"].predict(X)[0])
        if pkg.get("lgb") is not None:
            preds.append(pkg["lgb"].predict(X)[0])
        if not preds:
            return {"yield_kg_total": 5000.0, "yield_kg_m2": 5.0, "source": "stub"}

        raw_pred = float(np.mean(preds))
        if log_transform:
            yield_total = float(np.expm1(max(raw_pred, 0))) * max(area_m2, 1)
        else:
            yield_total = max(raw_pred, 0) * max(area_m2, 1)

        mape_cv = pkg.get("cv_mape", 99)
        source  = "m2_dag_retrain"

    yield_total = max(yield_total, 0)
    yield_m2    = yield_total / max(area_m2, 1)

    return {
        "yield_kg_total": round(yield_total, 1),
        "yield_kg_m2":    round(yield_m2, 4),
        "source":         source,
        "mape_cv":        mape_cv,
    }

def get_model_meta(crop_ko: str) -> Dict:
    pkg = _load(crop_ko)
    if pkg is None: return {"status":"stub","crop":crop_ko}
    return {"mape": pkg.get("mape"), "train_r2": pkg.get("train_r2"),
            "gate_pass": pkg.get("gate_pass"), "crop": crop_ko,
            "target": pkg.get("target")}

@dataclass
class YieldPrediction:
    yield_kg_total: float = 5000.0
    yield_kg_m2:    float = 5.0
    mape_cv:        float = 99.0
    source:         str   = "stub"

def predict(crop_ko: str, season_env: Dict[str, float],
            area_m2: float = 1000.0,
            farm_id: Optional[str] = None) -> YieldPrediction:
    r = predict_yield(crop_ko, season_env, area_m2, farm_id)
    return YieldPrediction(
        yield_kg_total=r["yield_kg_total"],
        yield_kg_m2=r["yield_kg_m2"],
        mape_cv=r.get("mape_cv", 99),
        source=r.get("source", "stub"))


# ── 클래스 API (test_models.py 호환) ──────────────────────────────────────────

@dataclass
class YieldPredictionV2:
    """신뢰 구간 + lag 피처 포함 버전 — M2YieldModel이 반환."""
    yield_kg_total: float = 5000.0
    yield_kg_m2:    float = 5.0
    lower_80:       float = 3.5    # 80% 예측 구간 하한
    upper_80:       float = 6.5    # 80% 예측 구간 상한
    mape_cv:        float = 99.0
    confidence:     float = 0.5
    source:         str   = "stub"


class M2YieldModel:
    """생육+환경 피처 → 수확량 예측 클래스 API (모델 없으면 수식 기반 stub)."""

    _DEFAULT_CROP  = "딸기"
    _BASE_YIELD_M2 = 5.0    # stub 기본 수확량 (kg/m²)

    def predict(
        self,
        growth_features: Dict[str, float],
        env_features: Dict[str, float],
        lag_7d:  Optional[float] = None,
        lag_14d: Optional[float] = None,
        crop_ko: str   = "딸기",
        area_m2: float = 1000.0,
        farm_id: Optional[str] = None,
    ) -> YieldPredictionV2:
        # 피처 통합
        season_env = {**env_features, **growth_features}
        if lag_7d  is not None:
            season_env["lag_7d_yield"]  = lag_7d
        if lag_14d is not None:
            season_env["lag_14d_yield"] = lag_14d

        result = predict_yield(crop_ko, season_env, area_m2, farm_id)
        base_m2 = result["yield_kg_m2"]

        # lag 블렌딩: 항상 적용 (모델/stub 무관) — 과거 실적 이력과 블렌딩
        lags = [v for v in (lag_7d, lag_14d) if v is not None]
        if lags:
            lag_mean = float(np.mean(lags))
            base_m2  = 0.5 * base_m2 + 0.5 * lag_mean

        # stub 모드일 때만 초장 기반 성장 계수 보정 적용
        if result.get("source") == "stub":
            # 초장 기반 성장 계수 보정 (plant_height 30cm → 계수 1.0 기준)
            ph = growth_features.get("plant_height", 0.0)
            if ph > 0:
                base_m2 *= min(1.5, max(0.5, ph / 30.0))

        base_m2 = max(base_m2, 0.01)

        # 80% 예측 구간: MAPE를 spread 추정에 사용
        mape_frac = float(result.get("mape_cv", 99)) / 100.0
        spread    = base_m2 * min(mape_frac * 0.8, 0.5)
        lower_80  = max(0.0, base_m2 - spread)
        upper_80  = base_m2 + spread

        return YieldPredictionV2(
            yield_kg_total=round(base_m2 * area_m2, 1),
            yield_kg_m2=round(base_m2, 4),
            lower_80=round(lower_80, 4),
            upper_80=round(upper_80, 4),
            mape_cv=float(result.get("mape_cv", 99.0)),
            confidence=round(min(0.9, max(0.3, 1.0 - mape_frac)), 3),
            source=result.get("source", "stub"),
        )
