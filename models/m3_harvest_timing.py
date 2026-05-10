"""M3 — 수확 시기 예측 (GDD 기반)

Growing Degree Days (GDD) 누적값이 작물별 목표치에 도달하는 날짜를 예측한다.
GDD_daily = max(0, T_mean - T_base)

작물별 목표 GDD (딸기 기준):
  - 딸기(strawberry):   1200 °C·d
  - 토마토(tomato):     1800 °C·d
  - 방울토마토:         1600 °C·d
  - 멜론(melon):        2000 °C·d

배포 게이트: 예측 오차 ± 5일 이내
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

T_BASE = 10.0   # base temperature (°C)

CROP_GDD_TARGET: dict[str, float] = {
    "strawberry":    1200.0,
    "tomato":        1800.0,
    "cherry_tomato": 1600.0,
    "melon":         2000.0,
}


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

    target = CROP_GDD_TARGET.get(crop_type, 1200.0)
    gdd_remaining = max(0.0, target - gdd_current)

    daily_gdd = max(0.0, avg_daily_temp - T_BASE)
    if daily_gdd <= 0:
        logger.warning("[M3] avg_daily_temp=%.1f ≤ T_base=%.1f — using T_base+1", avg_daily_temp, T_BASE)
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


def update_gdd(gdd_prev: float, t_max: float, t_min: float) -> float:
    """Accumulate one day's GDD.

    Args:
        gdd_prev: previous cumulative GDD
        t_max:    daily maximum temperature (°C)
        t_min:    daily minimum temperature (°C)
    """
    t_mean = (t_max + t_min) / 2.0
    daily = max(0.0, t_mean - T_BASE)
    return gdd_prev + daily
