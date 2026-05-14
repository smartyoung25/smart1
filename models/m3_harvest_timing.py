"""M3 — 수확 시기 예측 (GDD 기반)

Growing Degree Days (GDD) 누적값이 작물별 목표치에 도달하는 날짜를 예측한다.
GDD_daily = max(0, T_mean - T_base)

GDD 목표값과 기준온도는 growth_stats.json(extract_growth_stats.py 출력)에서 로드.
파일 없으면 하드코딩 폴백 사용.

배포 게이트: 예측 오차 +/- 5일 이내
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_GROWTH_STATS_PATH = Path(__file__).parent.parent / "api" / "data" / "growth_stats.json"

# 영문 crop_type → 한글 작목명 매핑
_CROP_EN_TO_KO: dict[str, str] = {
    "strawberry":    "딸기",
    "tomato":        "완숙토마토",
    "cherry_tomato": "방울토마토",
    "melon":         "참외",
    "cucumber":      "오이",
}

# 하드코딩 폴백 (growth_stats.json 없을 때)
_GDD_FALLBACK: dict[str, dict] = {
    "strawberry":    {"gdd_target": 1200.0, "base_temp": 6.0},
    "tomato":        {"gdd_target": 1800.0, "base_temp": 10.0},
    "cherry_tomato": {"gdd_target": 1600.0, "base_temp": 10.0},
    "melon":         {"gdd_target": 2000.0, "base_temp": 12.0},
    "cucumber":      {"gdd_target": 900.0,  "base_temp": 12.0},
}

T_BASE = 10.0   # 기본 기준온도 (단일 작목 호환용)


@lru_cache(maxsize=None)
def _load_growth_stats() -> dict:
    if not _GROWTH_STATS_PATH.exists():
        return {}
    try:
        return json.loads(_GROWTH_STATS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[M3] growth_stats.json 로드 실패: %s", e)
        return {}


def _get_gdd_params(crop_type: str) -> dict:
    """작목별 GDD 목표값과 기준온도 반환.

    growth_stats.json의 GDD_보정.fitted_gdd_to_harvest 우선,
    없으면 폴백 사용.
    """
    growth = _load_growth_stats()
    crop_ko = _CROP_EN_TO_KO.get(crop_type)
    if crop_ko and crop_ko in growth:
        gdd_info = growth[crop_ko].get("GDD_보정", {})
        fitted   = gdd_info.get("fitted_gdd_to_harvest")
        base     = gdd_info.get("base_temp_c")
        if fitted and base:
            return {"gdd_target": float(fitted), "base_temp": float(base)}

    return _GDD_FALLBACK.get(crop_type, {"gdd_target": 1200.0, "base_temp": 10.0})


CROP_GDD_TARGET: dict[str, float] = {k: v["gdd_target"] for k, v in _GDD_FALLBACK.items()}


@dataclass
class HarvestTimingPrediction:
    predicted_date: date
    days_remaining: int
    gdd_current: float
    gdd_target: float
    gdd_remaining: float
    confidence: float


def predict(
    crop_type: str,
    gdd_current: float,
    avg_daily_temp: float,
    reference_date: Optional[date] = None,
) -> HarvestTimingPrediction:
    """Predict harvest date from current GDD accumulation.

    Args:
        crop_type:        one of strawberry | tomato | cherry_tomato | melon
        gdd_current:      accumulated GDD so far (°C·d)
        avg_daily_temp:   recent average daily temperature used to project forward
        reference_date:   starting date for projection (defaults to today)
    """
    if reference_date is None:
        reference_date = date.today()

    params    = _get_gdd_params(crop_type)
    target    = params["gdd_target"]
    base_temp = params["base_temp"]
    gdd_remaining = max(0.0, target - gdd_current)

    daily_gdd = max(0.0, avg_daily_temp - base_temp)
    if daily_gdd <= 0:
        logger.warning("[M3] avg_daily_temp=%.1f <= T_base=%.1f — using T_base+1", avg_daily_temp, base_temp)
        daily_gdd = 1.0

    days_remaining = int(gdd_remaining / daily_gdd) if daily_gdd > 0 else 999
    predicted_date = reference_date + timedelta(days=days_remaining)

    # Confidence: higher when GDD accumulation is already well advanced
    progress = min(1.0, gdd_current / target)
    confidence = 0.50 + progress * 0.40   # 0.50 at start → 0.90 at maturity

    logger.info(
        "[M3] crop=%s gdd=%.0f/%.0f days_remaining=%d predicted=%s conf=%.2f",
        crop_type, gdd_current, target, days_remaining, predicted_date, confidence,
    )

    return HarvestTimingPrediction(
        predicted_date=predicted_date,
        days_remaining=days_remaining,
        gdd_current=round(gdd_current, 1),
        gdd_target=target,
        gdd_remaining=round(gdd_remaining, 1),
        confidence=round(confidence, 2),
    )


def update_gdd(
    gdd_prev: float,
    t_max: float,
    t_min: float,
    crop_type: str = "strawberry",
) -> float:
    """Accumulate one day's GDD.

    Args:
        gdd_prev:  previous cumulative GDD
        t_max:     daily maximum temperature (°C)
        t_min:     daily minimum temperature (°C)
        crop_type: crop identifier for base temperature lookup
    """
    t_mean    = (t_max + t_min) / 2.0
    base_temp = _get_gdd_params(crop_type)["base_temp"]
    daily     = max(0.0, t_mean - base_temp)
    return gdd_prev + daily
