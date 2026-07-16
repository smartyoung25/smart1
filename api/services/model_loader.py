"""ML 모델 로더 — 4-Stage 파이프라인 우선, 구형 pkl 폴백.

로드 우선순위:
  1. 신형 4-stage: models/artifacts/{crop_en}/stage2_yield.pkl + stage3_revenue_coef.pkl
  2. 구형 앙상블:  models/artifacts/{crop_en}_revenue_model.pkl
  3. 없으면 None → 호출측에서 stats_fallback

예측 흐름 (4-stage):
  env_dict → Stage2(XGBoost) → yield_per_m2/연간 → Stage3(Ridge) → revenue_per_m2/연간
  → /12 or /작기개월수 → monthly revenue_per_m2
"""
from __future__ import annotations

import json
import logging
import pickle
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:                                    # 게이트 단일 출처 (pipeline/gates.py)
    from pipeline.gates import evaluate_crop as _gate_evaluate_crop
except Exception:                       # 게이트 모듈 부재 시 기존 동작 유지(fail-open)
    _gate_evaluate_crop = None

logger = logging.getLogger(__name__)

ROOT          = Path(__file__).parent.parent.parent
ARTIFACTS_DIR = ROOT / "models" / "artifacts"

# 작목명 별칭 → 표준 작목명 정규화 (품종명 포함 표기 대응)
_CROP_ALIAS: dict[str, str] = {
    "딸기(설향)":      "딸기",
    "딸기(금실)":      "딸기",
    "딸기(매향)":      "딸기",
    "방울토마토(대추형)": "방울토마토",
    "완숙토마토(일반)":  "완숙토마토",
    "미등록":          "딸기",   # 기본값 폴백
}

# 한국어 품목명 → 영문 파일명 매핑
CROP_EN: dict[str, str] = {
    "딸기":       "strawberry",
    "방울토마토": "cherry_tomato",
    "완숙토마토": "tomato",
    "참외":       "melon",
    "파프리카":   "paprika",
    "오이":       "cucumber",    # 재학습 완료 (MAPE 22.8%, R² 0.826)
}

# 작목별 작기 개월 수 (연간 yield → 월간 환산)
_SEASON_MONTHS: dict[str, int] = {
    "딸기":       6,
    "방울토마토": 8,
    "완숙토마토": 8,
    "참외":       4,
    "파프리카":  10,
    "오이":       8,
}

# farm_id → 품목 매핑 (farmer.py _FARM_META와 동기화)
FARM_CROP: dict[str, str] = {
    "farm_001": "오이",
    "farm_002": "방울토마토",
    "farm_003": "딸기",
    "farm_004": "완숙토마토",
    "farm_005": "딸기",    # 기본값
}

try:
    import numpy as np
    import pandas as pd
    _ML_AVAILABLE = True
except ImportError:
    _ML_AVAILABLE = False
    logger.warning("[model_loader] numpy/pandas 없음 — ML 예측 비활성화")


def normalize_crop(crop_ko: str) -> str:
    """품종명 포함 작목명을 표준 작목명으로 정규화."""
    if crop_ko in _CROP_ALIAS:
        return _CROP_ALIAS[crop_ko]
    base = crop_ko.split("(")[0].strip()
    return base if base else crop_ko


def _patch_imputer(imputer) -> None:
    """sklearn 1.5+ 호환: 구버전으로 직렬화된 SimpleImputer에 _fill_dtype 속성 보정.

    sklearn 1.5부터 SimpleImputer.transform()이 self._fill_dtype를 참조.
    구버전 모델은 해당 속성이 없으므로 statistics_.dtype으로 채워준다.
    """
    if imputer is None:
        return
    if not hasattr(imputer, "_fill_dtype"):
        try:
            imputer._fill_dtype = imputer.statistics_.dtype
            logger.debug("[model_loader] SimpleImputer._fill_dtype 패치 적용")
        except Exception as exc:
            logger.warning("[model_loader] SimpleImputer 패치 실패: %s", exc)


# ---------------------------------------------------------------------------
# 4-Stage 모델 로드
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def load_4stage_model(crop_ko: str) -> Optional[dict]:
    """신형 4-stage 아티팩트 로드 (stage2_yield + stage3_revenue_coef).

    Returns:
        {"stage2": dict, "stage3": dict, "meta": dict, "crop_en": str} or None
    """
    if not _ML_AVAILABLE:
        return None
    crop_ko = normalize_crop(crop_ko)
    crop_en = CROP_EN.get(crop_ko)
    if not crop_en:
        return None

    s2_path   = ARTIFACTS_DIR / crop_en / "stage2_yield.pkl"
    s3_path   = ARTIFACTS_DIR / crop_en / "stage3_revenue_coef.pkl"
    meta_path = ARTIFACTS_DIR / crop_en / "pipeline_meta.json"

    if not (s2_path.exists() and s3_path.exists()):
        return None

    try:
        s2 = pickle.loads(s2_path.read_bytes())
        s3 = pickle.loads(s3_path.read_bytes())
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

        # ★ 게이트 미달(폴백 판정) 모델은 서빙하지 않는다 — None 반환 시 호출측이
        #   구형 앙상블 → stats_fallback(농진청 표준) 순으로 내려감.
        #   (구: registry 게이트가 서빙에 미연결이라 MAPE 60%대 모델도 그대로 서빙되던 문제)
        #   ※ 지표는 반드시 gates.evaluate_crop(권위=stage2_meta.json)로 판정할 것.
        #     meta(pipeline_meta.json)의 stage2.mape는 다른 학습 실행 결과일 수 있음.
        #     지표가 없는 구 아티팩트는 판정 불가 → 기존대로 서빙(fail-open).
        if _gate_evaluate_crop is not None:
            _v = _gate_evaluate_crop(ARTIFACTS_DIR, crop_en)
            if not _v["serve_m2"]:
                logger.warning("[model_loader] %s 4-stage 게이트 미달(%s) — M2 미서빙 → 폴백. 사유: %s",
                               crop_ko, _v["label"], "; ".join(_v["reasons"]))
                return None

        # sklearn 1.5+ 호환: SimpleImputer._fill_dtype 누락 시 보정
        _patch_imputer(s2.get("imputer"))
        logger.info("[model_loader] 4-stage 로드: %s (s2 feats=%d)",
                    crop_ko, len(s2.get("feature_cols", [])))
        return {"stage2": s2, "stage3": s3, "meta": meta, "crop_en": crop_en}
    except Exception as e:
        logger.error("[model_loader] 4-stage 로드 실패 %s: %s", crop_ko, e)
        return None


def _predict_4stage(bundle: dict, env_dict: dict, crop_ko: str) -> float:
    """4-stage 모델로 연간 revenue_per_m2 예측 후 월간 환산 반환.

    Stage2: 환경 피처 → yield_per_m2 (연간 kg/m²)
    Stage3: yield_per_m2 × price → revenue_per_m2 (연간 원/m²)
    반환:   revenue_per_m2 / 작기개월수  → 월간 원/m²
    """
    s2 = bundle["stage2"]
    s3 = bundle["stage3"]

    # ── Stage 2: env → yield_per_m2 ────────────────────────────────────────
    feat_cols = s2.get("feature_cols", [])

    # API 환경값을 Stage2 피처 형식으로 변환
    # *_std, n_harvest_months 등 누락 피처는 imputer가 훈련 중앙값으로 채움
    env_map = {
        "temp_internal_mean": env_dict.get("temp_internal_mean",  env_dict.get("temp_internal",  None)),
        "humidity_int_mean":  env_dict.get("humidity_int_mean",   env_dict.get("humidity_int",   None)),
        "co2_ppm_mean":       env_dict.get("co2_ppm_mean",        env_dict.get("co2_ppm",        None)),
        "solar_rad_mean":     env_dict.get("solar_rad_mean",      env_dict.get("solar_rad",      None)),
        "soil_temp_mean":     env_dict.get("soil_temp_mean",      env_dict.get("soil_temp",      None)),
        "gdd_monthly":        env_dict.get("gdd_monthly",         None),
    }
    # DataFrame 구성 — 누락 컬럼은 NaN (imputer가 중앙값으로 대체)
    row = {col: env_map.get(col, float("nan")) for col in feat_cols}
    X_df  = pd.DataFrame([row], columns=feat_cols)
    X_imp = s2["imputer"].transform(X_df)

    # ridge_cv_winner / ridge_fallback: StandardScaler 전처리 필요
    if "scaler" in s2:
        X_imp = s2["scaler"].transform(X_imp)

    model_type = s2.get("type", "xgb")
    if model_type == "xgb_lgb_ensemble" and "model_lgb" in s2:
        # XGB + LGB 앙상블 (0.5 : 0.5 평균)
        raw_xgb = float(s2["model"].predict(X_imp)[0])
        raw_lgb = float(s2["model_lgb"].predict(X_imp)[0])
        raw = 0.5 * raw_xgb + 0.5 * raw_lgb
    elif model_type == "lgb" and "model_lgb" in s2:
        raw = float(s2["model_lgb"].predict(X_imp)[0])
    else:
        raw = float(s2["model"].predict(X_imp)[0])

    yield_per_m2 = float(np.expm1(raw)) if s2.get("log_transform") else raw
    yield_per_m2 = max(0.0, yield_per_m2)

    # Quantile 구간 (P10/P90) — 모델 있을 때만
    yield_lower = yield_upper = None
    try:
        if "model_q10" in s2 and s2["model_q10"] is not None:
            raw_q10 = float(s2["model_q10"].predict(X_imp)[0])
            yield_lower = max(0.0, float(np.expm1(raw_q10)))
        if "model_q90" in s2 and s2["model_q90"] is not None:
            raw_q90 = float(s2["model_q90"].predict(X_imp)[0])
            yield_upper = max(0.0, float(np.expm1(raw_q90)))
    except Exception:
        pass

    # ── Stage 3: yield × price → revenue_per_m2 ────────────────────────────
    from api.data.stats_loader import get_price_krw_kg
    # Prophet 가격 예측 우선 — 없으면 price_stats.json 중앙값 폴백
    _price_med_static = float(s3.get("price_median", get_price_krw_kg(crop_ko)))
    try:
        from models.m4_revenue import M4RevenueModel
        _prophet_model = M4RevenueModel.load_for_crop(crop_ko)
        if _prophet_model._prophet is not None:
            _ph_mean, _, _ = _prophet_model.forecast_price(horizon_days=30)
            price_med = _ph_mean
            logger.debug("[4stage] Prophet 가격 사용: %s = %.0f원/kg", crop_ko, price_med)
        else:
            price_med = _price_med_static
    except Exception:
        price_med = _price_med_static

    ridge = s3.get("ridge")
    if ridge is not None:
        feat_names = s3.get("feature_names", ["log_yield_annual", "log_price_annual"])
        n_feats    = getattr(ridge, "n_features_in_", len(feat_names))

        # 피처 이름 기반으로 벡터 구성 (2-feature or 4-feature 자동 대응)
        feat_vec = []
        for fn in feat_names[:n_feats]:
            if fn == "log_yield_annual":
                feat_vec.append(float(np.log1p(yield_per_m2)))
            elif fn == "log_price_annual":
                feat_vec.append(float(np.log1p(price_med)))
            elif fn == "year_trend":
                feat_vec.append(1.0)   # 최신(2022) 기준 → trend 최대값
            elif fn == "log_n_harvest_months":
                nhm = _SEASON_MONTHS.get(normalize_crop(crop_ko), 8)
                feat_vec.append(float(np.log1p(nhm)))
            else:
                feat_vec.append(0.0)

        X3 = np.array([feat_vec])
        revenue_annual = float(np.expm1(ridge.predict(X3)[0]))
    else:
        revenue_annual = yield_per_m2 * price_med

    revenue_annual = max(0.0, revenue_annual)

    # 월간 환산: 연간 revenue ÷ 작기 개월 수
    season_months = _SEASON_MONTHS.get(normalize_crop(crop_ko), 8)
    revenue_monthly = revenue_annual / season_months

    logger.debug(
        "[4stage] %s yield=%.3f kg/m² revenue_annual=%.0f→monthly=%.0f 원/m²",
        crop_ko, yield_per_m2, revenue_annual, revenue_monthly,
    )
    return revenue_monthly


# ---------------------------------------------------------------------------
# 구형 앙상블 모델 로드 (폴백)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def load_model(crop_ko: str) -> Optional[dict]:
    """구형 {crop_en}_revenue_model.pkl 로드 (4-stage 없는 경우 폴백).

    crop_ko는 normalize_crop()으로 정규화 후 전달 권장.
    """
    if not _ML_AVAILABLE:
        return None
    crop_ko = normalize_crop(crop_ko)
    crop_en = CROP_EN.get(crop_ko)
    if not crop_en:
        return None
    pkl_path = ARTIFACTS_DIR / f"{crop_en}_revenue_model.pkl"
    if not pkl_path.exists():
        return None
    try:
        with open(pkl_path, "rb") as f:
            model_info = pickle.load(f)
        _patch_imputer(model_info.get("imputer"))
        logger.info("[model_loader] 구형 모델 로드: %s", pkl_path.name)
        return model_info
    except Exception as e:
        logger.error("[model_loader] 구형 모델 로드 실패 %s: %s", pkl_path.name, e)
        return None


def clear_model_cache() -> dict[str, int]:
    """로드된 모델 캐시를 모두 비운다. 재학습 후 새 아티팩트를 바로 반영할 때 사용.

    Returns:
        {"cleared_4stage": n, "cleared_legacy": n}
    """
    n1 = load_4stage_model.cache_info().currsize
    n2 = load_model.cache_info().currsize
    load_4stage_model.cache_clear()
    load_model.cache_clear()
    logger.info("[model_loader] 캐시 초기화: 4stage=%d, legacy=%d 항목 제거", n1, n2)
    return {"cleared_4stage": n1, "cleared_legacy": n2}


def _predict_from_model(model_info: dict, env_dict: dict, month: int) -> float:
    """구형 모델 dict로 단일 예측값 반환."""
    feat_cols = model_info["feature_cols"]
    row  = {**env_dict, "month": month}
    X_df = pd.DataFrame([row]).reindex(columns=feat_cols)
    X    = model_info["imputer"].transform(X_df)

    if model_info.get("type") == "ridge_fallback":
        if "scaler" in model_info:
            X = model_info["scaler"].transform(X)
        return float(model_info["model"].predict(X)[0])

    preds = []
    if "xgb_model" in model_info:
        preds.append(float(model_info["xgb_model"].predict(X)[0]))
    if "lgb_model" in model_info:
        preds.append(float(model_info["lgb_model"].predict(X)[0]))
    return float(np.mean(preds)) if preds else 0.0


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

def predict_revenue_per_m2(
    crop_ko: str,
    env_dict: dict,
    month: int = 6,
) -> Optional[float]:
    """환경 변수 dict로 월 m² 당 예측 매출 반환.

    로드 우선순위:
      1. 신형 4-stage (stage2_yield + stage3_revenue_coef)
      2. 구형 앙상블 pkl
      3. None → 호출측 stats_fallback

    Args:
        crop_ko:  한국어 품목명 (품종명 포함 가능 — 자동 정규화)
        env_dict: 환경 변수 dict
                  temp_internal(_mean), humidity_int(_mean), co2_ppm(_mean),
                  solar_rad(_mean), soil_temp(_mean), gdd_monthly
        month:    예측 월 (1~12) — 구형 모델 전용, 4-stage는 무시

    Returns:
        float (원/m²/월) if model available, None otherwise.
    """
    crop_ko = normalize_crop(crop_ko)

    # ① 신형 4-stage 우선
    bundle = load_4stage_model(crop_ko)
    if bundle is not None:
        try:
            val = _predict_4stage(bundle, env_dict, crop_ko)
            return max(0.0, val)
        except Exception as e:
            logger.warning("[model_loader] 4-stage 예측 오류 crop=%s: %s", crop_ko, e)

    # ② 구형 앙상블 폴백
    model_info = load_model(crop_ko)
    if model_info is not None:
        try:
            val = _predict_from_model(model_info, env_dict, month)
            return max(0.0, val)
        except Exception as e:
            logger.warning("[model_loader] 구형 모델 예측 오류 crop=%s: %s", crop_ko, e)

    return None


def predict_season_revenue(
    crop_ko: str,
    env_dict: dict,
    area_m2: float = 1000.0,
    season_months: int = 6,
) -> Optional[float]:
    """작기 전체 예측 매출 (월별 예측 합산).

    Returns:
        총 매출 (원) if model available, None otherwise.
    """
    crop_ko = normalize_crop(crop_ko)

    # 4-stage: 연간 revenue × area
    bundle = load_4stage_model(crop_ko)
    if bundle is not None:
        try:
            monthly_rev = _predict_4stage(bundle, env_dict, crop_ko)
            return max(0.0, monthly_rev * area_m2 * season_months)
        except Exception as e:
            logger.warning("[model_loader] 4-stage 작기 예측 오류 crop=%s: %s", crop_ko, e)

    # 구형: 월별 루프
    model_info = load_model(crop_ko)
    if model_info is None:
        return None
    try:
        total = 0.0
        start_month = _get_season_start(crop_ko)
        for i in range(season_months):
            m = (start_month + i - 1) % 12 + 1
            rev_pm2 = _predict_from_model(model_info, env_dict, m)
            total += max(0.0, rev_pm2) * area_m2
        return total
    except Exception as e:
        logger.warning("[model_loader] 구형 작기 예측 오류 crop=%s: %s", crop_ko, e)
        return None


def predict_yield_bounds(
    crop_ko: str,
    env_dict: dict,
) -> dict:
    """수확량 점 예측 + P10/P90 불확실성 구간 반환.

    Returns:
        {
            "yield_per_m2":  float,   # 중앙 예측 (kg/m²)
            "yield_lower":   float,   # P10 구간 (kg/m²), None if not available
            "yield_upper":   float,   # P90 구간 (kg/m²), None if not available
            "has_bounds":    bool,
        }
    """
    crop_ko = normalize_crop(crop_ko)
    bundle  = load_4stage_model(crop_ko)
    result  = {"yield_per_m2": None, "yield_lower": None, "yield_upper": None,
               "has_bounds": False}

    if bundle is None or not _ML_AVAILABLE:
        return result

    s2 = bundle["stage2"]
    feat_cols = s2.get("feature_cols", [])
    env_map = {
        "temp_internal_mean": env_dict.get("temp_internal_mean", env_dict.get("temp_internal")),
        "humidity_int_mean":  env_dict.get("humidity_int_mean",  env_dict.get("humidity_int")),
        "co2_ppm_mean":       env_dict.get("co2_ppm_mean",       env_dict.get("co2_ppm")),
        "solar_rad_mean":     env_dict.get("solar_rad_mean",     env_dict.get("solar_rad")),
        "soil_temp_mean":     env_dict.get("soil_temp_mean",     env_dict.get("soil_temp")),
    }
    row   = {col: env_map.get(col, float("nan")) for col in feat_cols}
    X_df  = pd.DataFrame([row], columns=feat_cols)
    X_imp = s2["imputer"].transform(X_df)
    if "scaler" in s2:
        X_imp = s2["scaler"].transform(X_imp)

    try:
        model_type = s2.get("type", "xgb")
        if model_type == "xgb_lgb_ensemble" and "model_lgb" in s2:
            raw = 0.5 * float(s2["model"].predict(X_imp)[0]) + \
                  0.5 * float(s2["model_lgb"].predict(X_imp)[0])
        elif model_type == "lgb" and "model_lgb" in s2:
            raw = float(s2["model_lgb"].predict(X_imp)[0])
        else:
            raw = float(s2["model"].predict(X_imp)[0])
        yield_pt = max(0.0, float(np.expm1(raw)) if s2.get("log_transform") else raw)
        result["yield_per_m2"] = round(yield_pt, 4)

        if s2.get("model_q10") is not None:
            result["yield_lower"] = round(max(0.0, float(np.expm1(
                s2["model_q10"].predict(X_imp)[0]))), 4)
        if s2.get("model_q90") is not None:
            result["yield_upper"] = round(max(0.0, float(np.expm1(
                s2["model_q90"].predict(X_imp)[0]))), 4)
        result["has_bounds"] = (result["yield_lower"] is not None and
                                result["yield_upper"] is not None)
    except Exception as e:
        logger.warning("[model_loader] predict_yield_bounds 오류 %s: %s", crop_ko, e)

    return result


def _get_season_start(crop_ko: str) -> int:
    """작목별 작기 시작 월."""
    return {
        "딸기":       11,
        "방울토마토":  3,
        "완숙토마토":  3,
        "참외":        4,
        "파프리카":    9,
        "오이":        3,
    }.get(crop_ko, 3)


def get_model_meta(crop_ko: str) -> dict:
    """로드된 모델 메타정보 반환.

    4-stage 있으면 stage2/3 메타, 없으면 구형 모델 메타 반환.
    """
    crop_ko = normalize_crop(crop_ko)

    # 4-stage 우선
    bundle = load_4stage_model(crop_ko)
    if bundle is not None:
        meta    = bundle.get("meta", {})
        s2_meta = meta.get("stage2", {})
        s3_meta = meta.get("stage3", {})
        return {
            "crop":           crop_ko,
            "status":         "loaded",
            "model_type":     "4stage",
            "train_r2":       s2_meta.get("cv_r2_mean"),
            "train_mape":     s2_meta.get("mape"),
            "feature_count":  s2_meta.get("feature_count"),
            "n_train":        s2_meta.get("n_train"),
            "stage2_mape":    s2_meta.get("mape"),
            "stage2_cv_r2":   s2_meta.get("cv_r2_mean"),
            "stage2_gate":    s2_meta.get("gate_passed", False),
            "stage2_n_train": s2_meta.get("n_train"),
            "stage2_area_from_registry": s2_meta.get("area_from_registry_count", 0),
            "stage3_mape":    s3_meta.get("mape"),
            "stage3_gate":    s3_meta.get("gate_passed", False),
            "price_median_krw_kg": bundle["stage3"].get("price_median"),
        }

    # 구형 폴백
    model_info = load_model(crop_ko)
    if model_info is None:
        return {"crop": crop_ko, "status": "no_model"}
    return {
        "crop":          crop_ko,
        "status":        "loaded",
        "model_type":    model_info.get("type", "legacy_ensemble"),
        "train_r2":      model_info.get("train_r2"),
        "train_mape":    model_info.get("train_mape"),
        "feature_count": len(model_info.get("feature_cols", [])),
        "n_train":       model_info.get("n_train"),
    }


def crop_from_farm(farm_id: str) -> str:
    """farm_id → 품목명 조회."""
    return FARM_CROP.get(farm_id, "딸기")
