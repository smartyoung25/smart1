"""ML 모델 로더 — 작목별 학습된 pkl 모델 로드 및 예측 인터페이스.

학습 파일: scripts/train_strawberry_pipeline.py, scripts/train_multi_crop_pipeline.py
결과물:    models/artifacts/{crop_en}_revenue_model.pkl

패턴:
  - @lru_cache로 프로세스 당 1회만 로드
  - pkl 없으면 None 반환 → 호출측에서 통계 폴백
  - numpy/pandas import 실패 시 전체 모듈 graceful 비활성화
"""
from __future__ import annotations

import logging
import pickle
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT          = Path(__file__).parent.parent.parent
ARTIFACTS_DIR = ROOT / "models" / "artifacts"

# 작목명 별칭 → 표준 작목명 정규화 (품종명 포함 표기 대응)
# "딸기(설향)", "딸기(금실)" 등 → "딸기"
_CROP_ALIAS: dict[str, str] = {
    "딸기(설향)": "딸기",
    "딸기(금실)": "딸기",
    "딸기(매향)": "딸기",
    "방울토마토(대추형)": "방울토마토",
    "완숙토마토(일반)": "완숙토마토",
    "미등록": "딸기",   # 기본값 폴백
}


def normalize_crop(crop_ko: str) -> str:
    """품종명 포함 작목명을 표준 작목명으로 정규화.

    예) "딸기(설향)" → "딸기",  "방울토마토" → "방울토마토" (변경 없음)
    """
    if crop_ko in _CROP_ALIAS:
        return _CROP_ALIAS[crop_ko]
    # 괄호 앞 텍스트만 추출 (e.g. "딸기(설향)" → "딸기")
    base = crop_ko.split("(")[0].strip()
    return base if base else crop_ko


# 한국어 품목명 → 영문 파일명 매핑
CROP_EN: dict[str, str] = {
    "딸기":       "strawberry",
    "방울토마토": "cherry_tomato",
    "완숙토마토": "tomato",
    "참외":       "melon",
    "파프리카":   "paprika",
    "오이":       "cucumber",    # 미학습 — None 반환
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


@lru_cache(maxsize=None)
def load_model(crop_ko: str) -> Optional[dict]:
    """작목별 pkl 모델 로드 (lru_cache — 프로세스 당 1회).

    crop_ko는 normalize_crop()으로 정규화 후 전달 권장.

    Returns:
        model_info dict if available, None otherwise.
    """
    if not _ML_AVAILABLE:
        return None
    crop_ko = normalize_crop(crop_ko)
    crop_en = CROP_EN.get(crop_ko)
    if not crop_en:
        return None
    pkl_path = ARTIFACTS_DIR / f"{crop_en}_revenue_model.pkl"
    if not pkl_path.exists():
        logger.warning("[model_loader] 모델 없음: %s", pkl_path.name)
        return None
    try:
        with open(pkl_path, "rb") as f:
            model_info = pickle.load(f)
        logger.info("[model_loader] %s 모델 로드 완료 (%s)",
                    crop_ko, pkl_path.name)
        return model_info
    except Exception as e:
        logger.error("[model_loader] 로드 실패 %s: %s", pkl_path.name, e)
        return None


def _predict_from_model(model_info: dict, env_dict: dict, month: int) -> float:
    """모델 정보 dict로 단일 예측값 반환."""
    feat_cols = model_info["feature_cols"]
    row = {**env_dict, "month": month}
    X_df = pd.DataFrame([row]).reindex(columns=feat_cols)
    X = model_info["imputer"].transform(X_df)

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


def predict_revenue_per_m2(
    crop_ko: str,
    env_dict: dict,
    month: int = 6,
) -> Optional[float]:
    """환경 변수 dict로 월 m² 당 예측 매출 반환.

    Args:
        crop_ko:  한국어 품목명 (품종명 포함 가능 — 자동 정규화)
        env_dict: 환경 변수 (temp_internal_mean, humidity_int_mean, co2_ppm_mean, ...)
        month:    예측 월 (1~12)

    Returns:
        float (원/m²/월) if model available, None otherwise.
    """
    crop_ko    = normalize_crop(crop_ko)
    model_info = load_model(crop_ko)
    if model_info is None:
        return None
    try:
        val = _predict_from_model(model_info, env_dict, month)
        return max(0.0, val)   # 음수 방지
    except Exception as e:
        logger.warning("[model_loader] 예측 오류 crop=%s: %s", crop_ko, e)
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
    crop_ko    = normalize_crop(crop_ko)
    model_info = load_model(crop_ko)
    if model_info is None:
        return None
    try:
        total = 0.0
        # 딸기 작기: 11~4월 (6개월), 방울토마토: 3~10월 (8개월)
        start_month = _get_season_start(crop_ko)
        for i in range(season_months):
            m = (start_month + i - 1) % 12 + 1
            rev_pm2 = _predict_from_model(model_info, env_dict, m)
            total += max(0.0, rev_pm2) * area_m2
        return total
    except Exception as e:
        logger.warning("[model_loader] 작기 예측 오류 crop=%s: %s", crop_ko, e)
        return None


def _get_season_start(crop_ko: str) -> int:
    """작목별 작기 시작 월."""
    return {
        "딸기":       11,  # 11월 정식
        "방울토마토":  3,  # 3월 시작
        "완숙토마토":  3,
        "참외":        4,
        "파프리카":    9,
        "오이":        3,
    }.get(crop_ko, 3)


def get_model_meta(crop_ko: str) -> dict:
    """로드된 모델 메타정보 반환 (type, train_r2, feature_count 등)."""
    crop_ko    = normalize_crop(crop_ko)
    model_info = load_model(crop_ko)
    if model_info is None:
        return {"crop": crop_ko, "status": "no_model"}
    return {
        "crop":          crop_ko,
        "status":        "loaded",
        "model_type":    model_info.get("type", "unknown"),
        "train_r2":      model_info.get("train_r2"),
        "train_mape":    model_info.get("train_mape"),
        "feature_count": len(model_info.get("feature_cols", [])),
        "n_train":       model_info.get("n_train"),
    }


def crop_from_farm(farm_id: str) -> str:
    """farm_id → 품목명 조회."""
    return FARM_CROP.get(farm_id, "딸기")
